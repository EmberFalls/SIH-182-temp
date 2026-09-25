"""Evidence-bound cross-chain bridge resolution for investigation v2.

A bridge boundary is only continued when a reviewed route and an exact protocol
message identifier connect the source and destination events.  Timing, amount,
or address similarity alone never permits a cross-chain continuation.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Protocol
import uuid

from pydantic import BaseModel, Field, field_validator, model_validator

from .canonical import canonical_sha256
from .domain import (
    AssertionReviewState,
    AssertionType,
    AssetRef,
    CanonicalTransfer,
    FlowSeed,
    FlowTerminalV2,
    FundFlowResultV2,
    SeedType,
    TerminalReason,
    TracePolicyV2,
    normalize_address,
)
from .flow_v2 import FundFlowEngineV2
from .models import Chain


class CrossChainEdgeType(str, Enum):
    BRIDGE_SOURCE = "BRIDGE_SOURCE"
    CROSS_CHAIN_LINK = "CROSS_CHAIN_LINK"
    BRIDGE_DESTINATION = "BRIDGE_DESTINATION"


class CrossChainLinkStatus(str, Enum):
    VERIFIED = "VERIFIED"
    UNRESOLVED = "UNRESOLVED"


class BridgeRouteCreateV2(BaseModel):
    bridge_entity_id: str
    protocol: str = Field(min_length=2, max_length=120)
    source_chain: Chain
    source_bridge_address: str = Field(min_length=20, max_length=100)
    destination_chain: Chain
    destination_bridge_address: str = Field(min_length=20, max_length=100)
    source_asset_contract: str | None = Field(default=None, min_length=1, max_length=100)
    destination_asset_contract: str | None = Field(default=None, min_length=1, max_length=100)
    route_evidence_id: str = Field(min_length=4, max_length=200)
    review_state: AssertionReviewState = AssertionReviewState.UNREVIEWED
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_route(self):
        if self.source_chain == self.destination_chain:
            raise ValueError("A cross-chain route must connect two different chains.")
        self.source_bridge_address = normalize_address(self.source_chain, self.source_bridge_address)
        self.destination_bridge_address = normalize_address(self.destination_chain, self.destination_bridge_address)
        if self.source_asset_contract:
            self.source_asset_contract = self.source_asset_contract.lower()
        if self.destination_asset_contract:
            self.destination_asset_contract = self.destination_asset_contract.lower()
        return self


class BridgeRouteV2(BridgeRouteCreateV2):
    id: str
    created_at: datetime
    evidence_hash_sha256: str = Field(min_length=64, max_length=64)


class CrossChainResolveRequestV2(BaseModel):
    route_id: str
    source_transfer: CanonicalTransfer
    destination_transfer: CanonicalTransfer
    message_id: str = Field(min_length=8, max_length=500)
    source_event_evidence_id: str = Field(min_length=4, max_length=200)
    destination_event_evidence_id: str = Field(min_length=4, max_length=200)
    source_transaction_uri: str | None = Field(default=None, max_length=1000)
    destination_transaction_uri: str | None = Field(default=None, max_length=1000)


class CrossChainLinkV2(BaseModel):
    id: str
    edge_type: CrossChainEdgeType = CrossChainEdgeType.CROSS_CHAIN_LINK
    status: CrossChainLinkStatus
    assertion_type: AssertionType
    route_id: str
    bridge_entity_id: str
    protocol: str
    source_transfer_id: str
    destination_transfer_id: str
    source_chain: Chain
    destination_chain: Chain
    source_transaction_id: str
    destination_transaction_id: str
    source_bridge_address: str
    destination_bridge_address: str
    destination_recipient_address: str
    source_asset: AssetRef
    destination_asset: AssetRef
    source_amount: Decimal = Field(gt=0)
    destination_amount: Decimal = Field(gt=0)
    source_timestamp: datetime
    destination_timestamp: datetime
    message_id: str | None = None
    source_event_evidence_id: str
    destination_event_evidence_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_hash_sha256: str = Field(min_length=64, max_length=64)
    created_at: datetime
    limitations: list[str] = Field(default_factory=list)

    @property
    def continuation_allowed(self) -> bool:
        return self.status == CrossChainLinkStatus.VERIFIED and self.assertion_type == AssertionType.VERIFIED and bool(self.message_id)


class CrossChainContinuationRequestV2(BaseModel):
    source_allocation_id: str = Field(min_length=4, max_length=120)
    source_attributed_amount: Decimal = Field(gt=0)


class CrossChainContinuationV2(BaseModel):
    link_id: str
    source_allocation_id: str
    destination_seed: FlowSeed
    source_attributed_amount: Decimal = Field(gt=0)
    destination_attributed_amount: Decimal = Field(gt=0)
    amount_conversion_note: str


class BridgeRouteStore(Protocol):
    def get_bridge_route_v2(self, route_id: str) -> BridgeRouteV2 | None: ...
    def get_entity(self, entity_id: str): ...


class CrossChainResolverV2:
    """Protocol-neutral exact-message resolver.

    Provider adapters can supply transfers and extracted protocol message IDs. This
    resolver deliberately does not attempt heuristic cross-chain matching.
    """

    VERSION = "1.0.0"

    def __init__(self, store: BridgeRouteStore) -> None:
        self.store = store

    def resolve(self, request: CrossChainResolveRequestV2, created_at: datetime) -> CrossChainLinkV2:
        route = self.store.get_bridge_route_v2(request.route_id)
        if route is None:
            raise ValueError("Bridge route not found.")
        entity = self.store.get_entity(route.bridge_entity_id)
        if entity is None or entity.entity_type.value != "BRIDGE":
            raise ValueError("Bridge route must reference a registered BRIDGE entity.")
        if route.review_state != AssertionReviewState.REVIEWED:
            raise ValueError("Bridge route must be reviewed before an exact continuation can be created.")
        source, destination = request.source_transfer, request.destination_transfer
        self._validate_route(route, source, destination)
        if not request.message_id.strip():
            raise ValueError("An exact bridge message identifier is required for continuation.")
        if destination.timestamp < source.timestamp:
            raise ValueError("Destination bridge event cannot precede its source event.")
        if destination.normalized_amount > source.normalized_amount:
            raise ValueError("Destination amount cannot exceed source amount for a fee-aware bridge continuation.")

        body = {
            "resolver_version": self.VERSION,
            "route_id": route.id,
            "source_transfer": source,
            "destination_transfer": destination,
            "message_id": request.message_id,
            "source_event_evidence_id": request.source_event_evidence_id,
            "destination_event_evidence_id": request.destination_event_evidence_id,
        }
        link_id = f"XCHAIN-{canonical_sha256(body)[:24].upper()}"
        evidence_ids = [
            route.route_evidence_id,
            request.source_event_evidence_id,
            request.destination_event_evidence_id,
            source.raw_evidence_id,
            destination.raw_evidence_id,
        ]
        return CrossChainLinkV2(
            id=link_id,
            status=CrossChainLinkStatus.VERIFIED,
            assertion_type=AssertionType.VERIFIED,
            route_id=route.id,
            bridge_entity_id=route.bridge_entity_id,
            protocol=route.protocol,
            source_transfer_id=source.id,
            destination_transfer_id=destination.id,
            source_chain=source.chain,
            destination_chain=destination.chain,
            source_transaction_id=source.transaction_id,
            destination_transaction_id=destination.transaction_id,
            source_bridge_address=source.destination_address,
            destination_bridge_address=destination.source_address,
            destination_recipient_address=destination.destination_address,
            source_asset=source.asset,
            destination_asset=destination.asset,
            source_amount=source.normalized_amount,
            destination_amount=destination.normalized_amount,
            source_timestamp=source.timestamp,
            destination_timestamp=destination.timestamp,
            message_id=request.message_id,
            source_event_evidence_id=request.source_event_evidence_id,
            destination_event_evidence_id=request.destination_event_evidence_id,
            evidence_ids=sorted(set(evidence_ids)),
            evidence_hash_sha256=canonical_sha256(body),
            created_at=created_at,
            limitations=[
                "The link establishes protocol-event correspondence, not beneficial ownership.",
                "Destination attribution is scaled by observed bridge output after any bridge fee.",
            ],
        )

    def unresolved_terminal(self, source_transfer: CanonicalTransfer, amount: Decimal, detail: str, parent_allocation_ids: list[str] | None = None, depth: int = 0) -> FlowTerminalV2:
        """Represent unsupported or insufficiently evidenced bridge use without loss."""
        return FlowTerminalV2(
            address=source_transfer.destination_address,
            amount=amount,
            reason=TerminalReason.BRIDGE_UNRESOLVED,
            depth=depth,
            parent_allocation_ids=parent_allocation_ids or [],
            detail=detail,
        )

    def continuation(self, link: CrossChainLinkV2, source_allocation_id: str, source_attributed_amount: Decimal) -> CrossChainContinuationV2:
        if not link.continuation_allowed:
            raise ValueError("Cross-chain continuation is blocked without a verified exact message link.")
        if source_attributed_amount <= 0:
            raise ValueError("Source attributed amount must be positive.")
        scaled = source_attributed_amount * (link.destination_amount / link.source_amount)
        seed = FlowSeed(
            id=f"SEED-{link.id}",
            address=link.destination_recipient_address,
            asset=link.destination_asset,
            amount=scaled,
            timestamp=link.destination_timestamp,
            seed_type=SeedType.TRANSACTION,
            source_transaction_id=link.destination_transaction_id,
            source_evidence_id=link.id,
        )
        return CrossChainContinuationV2(
            link_id=link.id,
            source_allocation_id=source_allocation_id,
            destination_seed=seed,
            source_attributed_amount=source_attributed_amount,
            destination_attributed_amount=scaled,
            amount_conversion_note="Destination allocation equals source attributed amount scaled by observed destination/source bridge amount; the difference is recorded as bridge fee or asset conversion.",
        )

    async def trace_destination(
        self,
        engine: FundFlowEngineV2,
        continuation: CrossChainContinuationV2,
        trace_policy: TracePolicyV2,
    ) -> FundFlowResultV2:
        """Continue the allocation from the verified destination bridge receipt."""
        return await engine.trace(continuation.destination_seed, trace_policy)


    @staticmethod
    def _asset_contract_matches(expected: str | None, actual: AssetRef) -> bool:
        return expected is None or (actual.contract_address or "").lower() == expected.lower()

    def _validate_route(self, route: BridgeRouteV2, source: CanonicalTransfer, destination: CanonicalTransfer) -> None:
        if source.chain != route.source_chain or destination.chain != route.destination_chain:
            raise ValueError("Transfers do not match the bridge route chains.")
        if source.destination_address != route.source_bridge_address:
            raise ValueError("Source transfer does not reach the reviewed source bridge address.")
        if destination.source_address != route.destination_bridge_address:
            raise ValueError("Destination transfer does not originate from the reviewed destination bridge address.")
        if not self._asset_contract_matches(route.source_asset_contract, source.asset):
            raise ValueError("Source asset does not match the reviewed bridge route.")
        if not self._asset_contract_matches(route.destination_asset_contract, destination.asset):
            raise ValueError("Destination asset does not match the reviewed bridge route.")


def new_bridge_route(payload: BridgeRouteCreateV2, created_at: datetime) -> BridgeRouteV2:
    body = {"payload": payload, "created_at": created_at}
    return BridgeRouteV2(
        id=f"BRIDGE-ROUTE-{uuid.uuid4().hex[:12].upper()}",
        created_at=created_at,
        evidence_hash_sha256=canonical_sha256(body),
        **payload.model_dump(),
    )