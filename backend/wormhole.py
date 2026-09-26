"""Wormhole EVM LogMessagePublished evidence collector.

Decodes the canonical Wormhole Core Contract event from a retained EVM transaction
receipt. It produces a VAA identifier (emitter chain / emitter / sequence) but does
not claim that a destination redemption occurred; the regular exact-event resolver
still requires that destination evidence.
"""
from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field

from .bridge_events import BridgeEventDirection, BridgeEventV2
from .canonical import canonical_sha256
from .domain import CanonicalTransfer, RawEvidenceArtifact

LOG_MESSAGE_PUBLISHED_TOPIC = "0x6eb224fb001ed210e379b335e35efe88672a8ce935d981a6896b27ffdf52a3b2"


class WormholeEvmExtractionRequestV2(BaseModel):
    raw_evidence_id: str = Field(min_length=4, max_length=200)
    transfer: CanonicalTransfer
    wormhole_chain_id: int = Field(ge=1, le=65535)
    core_contract: str = Field(pattern=r"^0x[a-fA-F0-9]{40}$")


class WormholeEvmMessageCollectorV2:
    VERSION = "wormhole-evm-log-v1"

    def extract(self, artifact: RawEvidenceArtifact, request: WormholeEvmExtractionRequestV2) -> BridgeEventV2:
        receipt_logs = artifact.metadata.get("receipt_logs") if isinstance(artifact.metadata, dict) else None
        if not isinstance(receipt_logs, list):
            raise ValueError("Evidence artifact does not retain an EVM transaction receipt log list.")
        core_contract = request.core_contract.lower()
        for log in receipt_logs:
            if not isinstance(log, dict) or str(log.get("address", "")).lower() != core_contract:
                continue
            topics = log.get("topics") or []
            if len(topics) < 2 or str(topics[0]).lower() != LOG_MESSAGE_PUBLISHED_TOPIC:
                continue
            emitter = str(topics[1])[-40:].lower()
            data = str(log.get("data", ""))
            if not data.startswith("0x") or len(data) < 66:
                raise ValueError("Wormhole LogMessagePublished log has no decodable sequence word.")
            try:
                sequence = int(data[2:66], 16)
                nonce = int(data[66:130], 16) if len(data) >= 130 else None
                consistency_level = int(data[194:258], 16) if len(data) >= 258 else None
            except ValueError as exc:
                raise ValueError("Wormhole LogMessagePublished log is malformed.") from exc
            message_id = f"{request.wormhole_chain_id}/{emitter}/{sequence}"
            body = {
                "protocol": "WORMHOLE", "message_id": message_id, "raw_evidence_id": artifact.id,
                "transfer": request.transfer, "core_contract": core_contract,
            }
            return BridgeEventV2(
                id=f"BRIDGE-EVENT-{canonical_sha256(body)[:24].upper()}",
                protocol="WORMHOLE", direction=BridgeEventDirection.SOURCE, message_id=message_id,
                transfer=request.transfer, raw_evidence_id=artifact.id, extractor_version=self.VERSION,
                extracted_at=datetime.now(timezone.utc), evidence_hash_sha256=canonical_sha256(body),
                metadata={"core_contract": core_contract, "emitter": emitter, "sequence": str(sequence),
                          **({"nonce": str(nonce)} if nonce is not None else {}),
                          **({"consistency_level": str(consistency_level)} if consistency_level is not None else {})},
                limitations=[
                    "This source event proves a Wormhole VAA identifier from the retained EVM receipt log.",
                    "A destination redemption event with the same VAA identifier is still required before cross-chain continuation.",
                ],
            )
        raise ValueError("No Wormhole LogMessagePublished event matched the supplied Core Contract in the retained receipt logs.")
