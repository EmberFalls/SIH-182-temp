"""Evidence-preserving adapters for configured blockchain read providers."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from .canonical import canonical_sha256
from .domain import (
    AssetRef,
    CanonicalTransfer,
    CoverageStatus,
    EvidenceCoverageRecord,
    ProviderAdapterResult,
    RawEvidenceArtifact,
    normalize_address,
)
from .models import Chain, TransferEvidence
from .tron import ProviderUnavailable


PARSER_NAME = "legacy-explorer-adapter"
PARSER_VERSION = "v3.0"
CANONICALIZATION_VERSION = "v3.0"


class ProviderAdapter(Protocol):
    """Formal read-only acquisition boundary used by V2 investigations."""

    async def outgoing_transfers(self, address: str, asset: AssetRef, limit: int, cursor: str | None = None) -> ProviderAdapterResult: ...
    async def transaction_transfers(self, transaction_hash: str, asset: AssetRef) -> ProviderAdapterResult: ...
    async def health(self) -> dict: ...
    def provider_capabilities(self) -> dict: ...


class LegacyExplorerAdapter:
    """Wrap an existing normalized v1 client without changing its public API."""

    def __init__(self, chain: Chain, client: object) -> None:
        self.chain = chain
        self.client = client

    async def outgoing_transfers(self, address: str, asset: AssetRef | str, limit: int, cursor: str | None = None) -> ProviderAdapterResult:
        """Collect a snapshot and state whether its coverage is complete.

        The string compatibility path exists only for the older callers. V2 passes
        an AssetRef so matching can preserve the contract/mint asset identity.
        """
        token_symbol = asset.symbol if isinstance(asset, AssetRef) else asset
        if self.chain == Chain.TRON:
            transfers, provenance = await self.client.outgoing_trc20_transfers(address, token_symbol, limit)
        else:
            transfers, provenance = await self.client.outgoing_erc20_transfers(address, token_symbol, limit)
        evidence = self._evidence(provenance)
        canonical = [self._transfer(item, evidence.id, index) for index, item in enumerate(transfers)]
        coverage = self._coverage(address, asset if isinstance(asset, AssetRef) else None, provenance, canonical, bounded=bool(provenance.get("bounded_by_limit") or len(transfers) >= limit))
        return ProviderAdapterResult(provider=str(provenance.get("provider", "unknown")), chain=self.chain, transfers=canonical, evidence=evidence, complete=coverage.complete, coverage=coverage, warnings=coverage.warnings)

    async def transaction_transfers(self, transaction_hash: str, asset: AssetRef) -> ProviderAdapterResult:
        if self.chain == Chain.TRON and hasattr(self.client, "transaction_trc20_transfers"):
            transfers, provenance = await self.client.transaction_trc20_transfers(transaction_hash, asset.symbol, asset.contract_address, asset.decimals)
        elif self.chain in {Chain.ETHEREUM, Chain.BNB_CHAIN, Chain.POLYGON} and hasattr(self.client, "transaction_erc20_transfers"):
            transfers, provenance = await self.client.transaction_erc20_transfers(transaction_hash, asset.symbol, asset.contract_address, asset.decimals)
        else:
            raise ProviderUnavailable(f"{self.chain.value} does not yet provide token Transfer events by transaction hash.")
        evidence = self._evidence(provenance)
        canonical = [self._transfer(item, evidence.id, index) for index, item in enumerate(transfers)]
        coverage = self._coverage(transaction_hash, asset, provenance, canonical, bounded=False)
        return ProviderAdapterResult(provider=str(provenance.get("provider", "unknown")), chain=self.chain, transfers=canonical, evidence=evidence, complete=coverage.complete, coverage=coverage, warnings=coverage.warnings)

    async def health(self) -> dict:
        return {"provider": getattr(self.client, "provider_name", self.chain.value), "configured": bool(getattr(self.client, "configured", False))}

    def provider_capabilities(self) -> dict:
        return {"outgoing_token_transfers": True, "transaction_token_transfers": hasattr(self.client, "transaction_erc20_transfers") or hasattr(self.client, "transaction_trc20_transfers"), "pagination": True}
    def _evidence(self, provenance: dict) -> RawEvidenceArtifact:
        safe_provenance = self._redact_secrets(provenance)
        raw_payload = safe_provenance.get("raw_responses")
        request_provenance = {key: value for key, value in safe_provenance.items() if key != "raw_responses"}
        fingerprint = canonical_sha256({"chain": self.chain.value, "request": request_provenance})
        retrieved_text = safe_provenance.get("retrieved_at")
        retrieved_at = datetime.fromisoformat(retrieved_text.replace("Z", "+00:00")) if isinstance(retrieved_text, str) else datetime.now(timezone.utc)
        return RawEvidenceArtifact(
            id=f"EVID-{fingerprint[:20].upper()}", kind="provider_response" if raw_payload is not None else "provider_response_metadata",
            provider=str(safe_provenance.get("provider", "unknown")), retrieved_at=retrieved_at,
            request_fingerprint=fingerprint, content_hash_sha256=canonical_sha256(raw_payload) if raw_payload is not None else None,
            source_uri=safe_provenance.get("endpoint"),
            metadata={**request_provenance, "parser_name": PARSER_NAME, "parser_version": PARSER_VERSION, "canonicalization_version": CANONICALIZATION_VERSION, "raw_payload": raw_payload},
        )

    @classmethod
    def _redact_secrets(cls, value):
        if isinstance(value, dict):
            return {key: cls._redact_secrets(item) for key, item in value.items() if key.lower() not in {"apikey", "api_key", "authorization", "x-api-key", "tron-pro-api-key"}}
        if isinstance(value, list):
            return [cls._redact_secrets(item) for item in value]
        return value
    def _coverage(self, subject: str, asset: AssetRef | None, provenance: dict, transfers: list[CanonicalTransfer], bounded: bool) -> EvidenceCoverageRecord:
        truncated = bool(provenance.get("pagination_truncated"))
        has_more = bool(provenance.get("has_more") or provenance.get("next_cursor"))
        if truncated:
            status, reason = CoverageStatus.PROVIDER_TRUNCATED, "Provider page cap or response limit prevented collection of the full result set."
        elif has_more or bounded:
            status, reason = CoverageStatus.BOUNDED, "Acquisition was intentionally bounded by the trace request limit."
        else:
            status, reason = CoverageStatus.COMPLETE, None
        timestamps = [item.timestamp for item in transfers]
        blocks = [item.block_number for item in transfers if item.block_number is not None]
        retrieved = provenance.get("retrieved_at")
        retrieved_at = datetime.fromisoformat(retrieved.replace("Z", "+00:00")) if isinstance(retrieved, str) else datetime.now(timezone.utc)
        warnings = [] if status == CoverageStatus.COMPLETE else [f"COVERAGE_{status.value}"]
        return EvidenceCoverageRecord(
            id=f"COVER-{canonical_sha256({'chain': self.chain.value, 'subject': subject, 'provenance': self._redact_secrets(provenance)})[:20].upper()}",
            chain=self.chain, subject=subject, asset=asset, provider=str(provenance.get("provider", "unknown")),
            collected_start=min(timestamps) if timestamps else None, collected_end=max(timestamps) if timestamps else None,
            collection_start_block=min(blocks) if blocks else None, collection_end_block=max(blocks) if blocks else None,
            pages_collected=int(provenance.get("pages_retrieved", 1)), complete=status == CoverageStatus.COMPLETE,
            coverage_status=status, reason_incomplete=reason, has_more=has_more, next_cursor=provenance.get("next_cursor"),
            warnings=warnings, retrieved_at=retrieved_at,
        )

    def _transfer(self, transfer: TransferEvidence, evidence_id: str, index: int) -> CanonicalTransfer:
        if transfer.token_decimals is None:
            raise ProviderUnavailable("Provider evidence is missing verified token decimals; canonicalisation refuses to infer decimals from an observed amount.")
        transaction_id = f"TX-{self.chain.value}-{transfer.transaction_hash.lower()}"
        asset = AssetRef(chain=self.chain, asset_type="token", symbol=transfer.token_symbol, contract_address=transfer.token_contract or None, token_standard=transfer.token_standard or ("TRC20" if self.chain == Chain.TRON else "ERC20"), decimals=transfer.token_decimals)
        transfer_id = f"XFER-{canonical_sha256({'tx': transaction_id, 'from': normalize_address(self.chain, transfer.source_address), 'to': normalize_address(self.chain, transfer.destination_address), 'asset_key': asset.asset_key, 'log_index': transfer.log_index, 'index': index})[:24].upper()}"
        return CanonicalTransfer(
            id=transfer_id, transaction_id=transaction_id, chain=self.chain, source_address=transfer.source_address, destination_address=transfer.destination_address,
            asset=asset, raw_amount=transfer.amount, normalized_amount=transfer.amount, timestamp=transfer.timestamp, block_number=transfer.block_number,
            log_index=transfer.log_index, transaction_index=transfer.transaction_index, raw_evidence_id=evidence_id,
            parser_name=PARSER_NAME, parser_version=PARSER_VERSION, canonicalization_version=CANONICALIZATION_VERSION,
        )
