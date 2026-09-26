"""Adapters that expose v1 explorer clients through the canonical Phase 1 boundary."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Protocol

from .canonical import canonical_sha256
from .domain import AssetRef, CanonicalTransaction, CanonicalTransfer, ProviderAdapterResult, RawEvidenceArtifact, normalize_address
from .models import Chain, TransferEvidence
from .tron import ProviderUnavailable


class TransferProviderAdapter(Protocol):
    async def outgoing_transfers(self, address: str, token_symbol: str, limit: int) -> ProviderAdapterResult: ...


class LegacyExplorerAdapter:
    """Wrap an existing normalized v1 client without changing its public API."""

    def __init__(self, chain: Chain, client: object) -> None:
        self.chain = chain
        self.client = client

    async def outgoing_transfers(self, address: str, token_symbol: str, limit: int) -> ProviderAdapterResult:
        if self.chain == Chain.TRON:
            transfers, provenance = await self.client.outgoing_trc20_transfers(address, token_symbol, limit)
        else:
            transfers, provenance = await self.client.outgoing_erc20_transfers(address, token_symbol, limit)
        evidence = self._evidence(provenance)
        canonical = [self._transfer(item, evidence.id, index) for index, item in enumerate(transfers)]
        complete = not bool(provenance.get("pagination_truncated"))
        warnings = ["PARTIAL_PROVIDER_DATA"] if not complete else []
        return ProviderAdapterResult(provider=str(provenance.get("provider", "unknown")), chain=self.chain, transfers=canonical, evidence=evidence, complete=complete, warnings=warnings)

    async def transaction_transfers(self, transaction_hash: str, asset: AssetRef) -> ProviderAdapterResult:
        if self.chain == Chain.TRON and hasattr(self.client, "transaction_trc20_transfers"):
            transfers, provenance = await self.client.transaction_trc20_transfers(transaction_hash, asset.symbol, asset.contract_address, asset.decimals)
        elif self.chain in {Chain.ETHEREUM, Chain.BNB_CHAIN, Chain.POLYGON} and hasattr(self.client, "transaction_erc20_transfers"):
            transfers, provenance = await self.client.transaction_erc20_transfers(transaction_hash, asset.symbol, asset.contract_address, asset.decimals)
        else:
            raise ProviderUnavailable(f"{self.chain.value} does not yet provide token Transfer events by transaction hash.")
        evidence = self._evidence(provenance)
        canonical = [self._transfer(item, evidence.id, index) for index, item in enumerate(transfers)]
        return ProviderAdapterResult(provider=str(provenance.get("provider", "unknown")), chain=self.chain, transfers=canonical, evidence=evidence, complete=True, warnings=[])
    def _evidence(self, provenance: dict) -> RawEvidenceArtifact:
        safe_provenance = self._redact_secrets(provenance)
        fingerprint = canonical_sha256({"chain": self.chain.value, "provenance": safe_provenance})
        retrieved_text = safe_provenance.get("retrieved_at")
        retrieved_at = datetime.fromisoformat(retrieved_text.replace("Z", "+00:00")) if isinstance(retrieved_text, str) else datetime.now().astimezone()
        return RawEvidenceArtifact(
            id=f"EVID-{fingerprint[:20].upper()}", kind="provider_response_metadata", provider=str(safe_provenance.get("provider", "unknown")),
            retrieved_at=retrieved_at, request_fingerprint=fingerprint, source_uri=safe_provenance.get("endpoint"), metadata=safe_provenance,
        )

    @classmethod
    def _redact_secrets(cls, value):
        if isinstance(value, dict):
            return {key: cls._redact_secrets(item) for key, item in value.items() if key.lower() not in {"apikey", "api_key", "authorization", "x-api-key", "tron-pro-api-key"}}
        if isinstance(value, list):
            return [cls._redact_secrets(item) for item in value]
        return value
    def _transfer(self, transfer: TransferEvidence, evidence_id: str, index: int) -> CanonicalTransfer:
        transaction_id = f"TX-{self.chain.value}-{transfer.transaction_hash.lower()}"
        decimals = self._decimals(transfer.amount)
        asset = AssetRef(chain=self.chain, symbol=transfer.token_symbol, contract_address=transfer.token_contract or None, decimals=decimals)
        transfer_id = f"XFER-{canonical_sha256({'tx': transaction_id, 'from': normalize_address(self.chain, transfer.source_address), 'to': normalize_address(self.chain, transfer.destination_address), 'asset': asset, 'index': index})[:24].upper()}"
        CanonicalTransaction(id=transaction_id, chain=self.chain, tx_hash=transfer.transaction_hash, block_number=transfer.block_number, timestamp=transfer.timestamp, confirmed=transfer.confirmed, raw_evidence_id=evidence_id)
        return CanonicalTransfer(
            id=transfer_id, transaction_id=transaction_id, chain=self.chain, source_address=transfer.source_address, destination_address=transfer.destination_address,
            asset=asset, raw_amount=transfer.amount, normalized_amount=transfer.amount, timestamp=transfer.timestamp, raw_evidence_id=evidence_id,
        )

    @staticmethod
    def _decimals(value: Decimal) -> int:
        return max(0, -value.as_tuple().exponent)
