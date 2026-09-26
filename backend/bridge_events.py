"""Normalized bridge-event extraction for investigation v2.

This module accepts structured event facts retained inside a raw-evidence artifact. It
never matches bridge deposits and withdrawals by amount, time, or recipient. A bridge
message identifier must be supplied by a protocol-aware collector before the event can
be used to continue a trace.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Protocol
import uuid

from pydantic import BaseModel, Field, model_validator

from .canonical import canonical_sha256
from .domain import CanonicalTransfer, RawEvidenceArtifact


class BridgeEventDirection(str, Enum):
    SOURCE = "SOURCE"
    DESTINATION = "DESTINATION"


class BridgeEventExtractionRequestV2(BaseModel):
    protocol: str = Field(min_length=2, max_length=120)
    direction: BridgeEventDirection
    raw_evidence_id: str = Field(min_length=4, max_length=200)
    transfer: CanonicalTransfer


class BridgeEventV2(BaseModel):
    id: str
    protocol: str
    direction: BridgeEventDirection
    message_id: str = Field(min_length=8, max_length=500)
    transfer: CanonicalTransfer
    raw_evidence_id: str
    extractor_version: str
    extracted_at: datetime
    evidence_hash_sha256: str = Field(min_length=64, max_length=64)
    metadata: dict[str, str] = Field(default_factory=dict)
    limitations: list[str] = Field(default_factory=list)


class BridgeEventStore(Protocol):
    def get_raw_evidence_artifact_v2(self, artifact_id: str) -> RawEvidenceArtifact | None: ...
    def save_bridge_event_v2(self, event: BridgeEventV2) -> BridgeEventV2: ...
    def get_bridge_event_v2(self, event_id: str) -> BridgeEventV2 | None: ...


class NormalizedBridgeEventExtractorV2:
    """Extract an exact protocol message ID from a preserved normalized event.

    Collectors place protocol-decoded event fields under ``metadata.bridge_event``.
    The contract intentionally rejects arbitrary transaction data: production protocol
    decoders must retain their raw response and place the decoded exact message ID in
    this evidence envelope.
    """

    VERSION = "normalized-bridge-event-v1"

    def extract(
        self,
        artifact: RawEvidenceArtifact,
        request: BridgeEventExtractionRequestV2,
        extracted_at: datetime | None = None,
    ) -> BridgeEventV2:
        payload = artifact.metadata.get("bridge_event") if isinstance(artifact.metadata, dict) else None
        if not isinstance(payload, dict):
            raise ValueError("Evidence artifact has no normalized bridge_event metadata.")
        protocol = str(payload.get("protocol", "")).strip()
        if protocol.casefold() != request.protocol.strip().casefold():
            raise ValueError("Bridge event protocol does not match the requested protocol.")
        message_id = str(payload.get("message_id", "")).strip()
        if len(message_id) < 8:
            raise ValueError("Bridge event evidence does not contain an exact message identifier.")
        direction = str(payload.get("direction", "")).upper()
        if direction and direction != request.direction.value:
            raise ValueError("Bridge event direction does not match the requested direction.")
        transaction_id = str(payload.get("transaction_id", "")).strip()
        transaction_hash = str(payload.get("transaction_hash", "")).strip().lower()
        if transaction_id and transaction_id != request.transfer.transaction_id:
            raise ValueError("Bridge event transaction ID does not match the supplied transfer.")
        if transaction_hash and transaction_hash not in request.transfer.transaction_id.lower():
            raise ValueError("Bridge event transaction hash does not match the supplied transfer.")
        recorded_transfer_id = str(payload.get("transfer_id", "")).strip()
        if recorded_transfer_id and recorded_transfer_id != request.transfer.id:
            raise ValueError("Bridge event transfer ID does not match the supplied transfer.")

        body = {
            "protocol": protocol,
            "direction": request.direction.value,
            "message_id": message_id,
            "raw_evidence_id": artifact.id,
            "transfer": request.transfer,
            "extractor_version": self.VERSION,
        }
        return BridgeEventV2(
            id=f"BRIDGE-EVENT-{canonical_sha256(body)[:24].upper()}",
            protocol=protocol,
            direction=request.direction,
            message_id=message_id,
            transfer=request.transfer,
            raw_evidence_id=artifact.id,
            extractor_version=self.VERSION,
            extracted_at=extracted_at or datetime.now(timezone.utc),
            evidence_hash_sha256=canonical_sha256(body),
            metadata={
                key: str(value) for key, value in payload.items()
                if key in {"emitter", "sequence", "nonce", "transaction_hash", "transaction_id", "transfer_id"}
                and value is not None
            },
            limitations=[
                "The event confirms an exact protocol message identifier only when its normalized fields are retained in the evidence artifact.",
                "It does not establish beneficial ownership of either source or destination wallet.",
            ],
        )


class BridgeEventResolveRequestV2(BaseModel):
    route_id: str
    source_event_id: str
    destination_event_id: str

    @model_validator(mode="after")
    def validate_events_differ(self):
        if self.source_event_id == self.destination_event_id:
            raise ValueError("Source and destination bridge events must be different records.")
        return self
