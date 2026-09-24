from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


class Chain(str, Enum):
    TRON = "TRON"
    ETHEREUM = "ETHEREUM"
    BNB_CHAIN = "BNB_CHAIN"
    POLYGON = "POLYGON"
    BITCOIN = "BITCOIN"
    SOLANA = "SOLANA"


class CaseCreate(BaseModel):
    title: str = Field(min_length=3, max_length=160)
    suspect_wallet: str = Field(min_length=34, max_length=42)
    chain: Chain = Chain.TRON
    token_symbol: str = Field(default="USDT", min_length=2, max_length=12)
    disputed_amount: Decimal | None = Field(default=None, ge=0)
    incident_start: datetime | None = None
    incident_end: datetime | None = None
    fir_number: str | None = Field(default=None, max_length=80)
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def chain_address_match(self):
        if self.chain == Chain.TRON and not (self.suspect_wallet.startswith("T") and len(self.suspect_wallet) == 34):
            raise ValueError("TRON addresses must be 34-character Base58 addresses beginning with T.")
        if self.chain in {Chain.ETHEREUM, Chain.BNB_CHAIN, Chain.POLYGON} and not (self.suspect_wallet.startswith("0x") and len(self.suspect_wallet) == 42):
            raise ValueError("EVM addresses must be 42-character hexadecimal addresses beginning with 0x.")
        if self.chain == Chain.BITCOIN and not (self.suspect_wallet.startswith(("1", "3", "bc1")) and 26 <= len(self.suspect_wallet) <= 90):
            raise ValueError("Bitcoin addresses must be a valid-looking Base58 or bech32 address.")
        if self.chain == Chain.SOLANA and not (32 <= len(self.suspect_wallet) <= 44 and not self.suspect_wallet.startswith("0x")):
            raise ValueError("Solana addresses must be a 32-44 character base58 address.")
        if self.incident_start and self.incident_start.tzinfo is None:
            raise ValueError("incident_start must include a timezone, for example 2026-09-24T09:00:00Z.")
        if self.incident_end and self.incident_end.tzinfo is None:
            raise ValueError("incident_end must include a timezone, for example 2026-09-24T09:00:00Z.")
        return self

    @field_validator("token_symbol")
    @classmethod
    def normalized_token(cls, value: str) -> str:
        return value.upper()


class CaseSummary(BaseModel):
    id: str
    title: str
    suspect_wallet: str
    chain: Chain
    token_symbol: str
    disputed_amount: Decimal | None
    incident_start: datetime | None
    incident_end: datetime | None
    fir_number: str | None
    notes: str | None
    case_status: Literal["OPEN", "UNDER_REVIEW", "ACTION_READY", "CLOSED"] = "OPEN"
    created_at: datetime


class TraceRequest(BaseModel):
    max_hops: int = Field(default=3, ge=1, le=5)
    max_transfers_per_wallet: int = Field(default=100, ge=1, le=500)


class CaseUpdate(BaseModel):
    case_status: Literal["OPEN", "UNDER_REVIEW", "ACTION_READY", "CLOSED"] | None = None
    notes: str | None = Field(default=None, max_length=2000)


class CaseNoteCreate(BaseModel):
    note: str = Field(min_length=1, max_length=4000)


class CaseNote(BaseModel):
    id: str
    case_id: str
    author: str
    note: str
    created_at: datetime


class LabelSource(BaseModel):
    url: str = Field(min_length=8, max_length=1000)
    source_name: str = Field(min_length=2, max_length=160)
    observed_at: datetime


class VaspLabelCreate(BaseModel):
    address: str = Field(min_length=20, max_length=80)
    chain: Chain
    vasp_name: str = Field(min_length=2, max_length=160)
    entity_kind: Literal["vasp", "bridge", "mixer", "swap"] = "vasp"
    label_type: Literal["hot_wallet", "deposit_address", "cluster", "bridge_contract", "mixer", "swap_service"]
    confidence: Literal["verified", "reviewed"]
    source: LabelSource
    reviewer: str = Field(min_length=2, max_length=160)
    expires_at: datetime | None = None


class VaspLabel(VaspLabelCreate):
    id: str
    created_at: datetime
    review_status: Literal["APPROVED", "REJECTED", "EXPIRED", "CONFLICT"] = "APPROVED"


class LabelReview(BaseModel):
    status: Literal["APPROVED", "REJECTED", "EXPIRED"]
    rationale: str = Field(min_length=3, max_length=1000)


class LabelReviewEvent(BaseModel):
    label_id: str
    reviewer: str
    status: Literal["APPROVED", "REJECTED", "EXPIRED"]
    rationale: str
    created_at: datetime


class LabelImportResult(BaseModel):
    imported: list[VaspLabel]
    rejected: list[str]


class TransferEvidence(BaseModel):
    transaction_hash: str
    source_address: str
    destination_address: str
    token_symbol: str
    token_contract: str
    amount: Decimal
    timestamp: datetime
    block_number: int | None
    confirmed: bool
    provider: str
    retrieved_at: datetime


class GraphNode(BaseModel):
    address: str
    chain: Chain
    role: Literal["suspect", "observed", "vasp", "bridge", "mixer", "swap"]
    label: str | None = None
    label_evidence: VaspLabel | None = None
    hop: int = 0
    case_inflow: Decimal = Decimal("0")
    case_outflow: Decimal = Decimal("0")
    explorer_url: str | None = None


class VaspCandidate(BaseModel):
    label_id: str
    vasp_name: str
    address: str
    hop: int
    label_type: str
    evidence_grade: Literal["verified", "reviewed"]
    supporting_transaction: str
    attributed_amount: Decimal = Decimal("0")
    priority_score: float = 0.0
    ranking_reason: str = ""


class GraphEdge(BaseModel):
    id: str
    transaction_hash: str
    source: str
    target: str
    hop: int
    token_symbol: str
    token_contract: str
    transfer_amount: Decimal
    attributed_amount: Decimal
    timestamp: datetime
    block_number: int | None
    confirmed: bool
    provider: str
    retrieved_at: datetime
    explorer_url: str | None = None
    relationship: Literal["transfer", "vasp_receipt", "bridge_interaction"] = "transfer"


class TracePath(BaseModel):
    candidate_label_id: str
    candidate_address: str
    hop: int
    node_addresses: list[str]
    edge_ids: list[str]


class TraceFrontier(BaseModel):
    address: str
    hop: int
    reason: Literal["provider_failure", "no_matching_outbound_transfer", "hop_limit", "wallet_query_limit"]
    detail: str
    explorer_url: str | None = None


class TraceGraph(BaseModel):
    root_address: str
    edges: list[GraphEdge] = Field(default_factory=list)
    paths: list[TracePath] = Field(default_factory=list)
    frontiers: list[TraceFrontier] = Field(default_factory=list)


class FlowAllocation(BaseModel):
    transaction_hash: str
    source_address: str
    destination_address: str
    transfer_amount: Decimal
    attributed_amount: Decimal
    allocation_method: Literal["conservative_fifo"] = "conservative_fifo"


class FlowAnalysis(BaseModel):
    starting_amount: Decimal
    allocated_amount: Decimal
    unallocated_amount: Decimal
    allocations: list[FlowAllocation]
    endpoint_amounts: dict[str, Decimal]
    method_note: str


class RiskAlert(BaseModel):
    code: Literal["rapid_movement", "peeling_chain", "mixer_interaction", "bridge_interaction", "high_fanout"]
    severity: Literal["low", "medium", "high"]
    description: str
    supporting_transactions: list[str]


class CrossCaseAlert(BaseModel):
    related_case_id: str
    shared_addresses: list[str]
    related_run_id: str
    severity: Literal["medium", "high"]
    description: str


class BridgeObservation(BaseModel):
    transaction_hash: str
    bridge_name: str
    source_address: str
    bridge_address: str
    source_chain: Chain
    status: Literal["OBSERVED_SOURCE_BRIDGE_NOT_LINKED"]
    next_evidence_needed: str


class SahyogDraft(BaseModel):
    draft_id: str
    case_id: str
    run_id: str
    vasp_name: str
    target_address: str
    relevant_transactions: list[str]
    attributed_amount: Decimal
    recommended_action: Literal["KYC_AND_TRANSACTION_LOGS", "PRESERVATION_REQUEST"]
    status: Literal["DRAFT_REQUIRES_INVESTIGATOR_REVIEW"]
    evidence_summary: str


class TraceResult(BaseModel):
    run_id: str
    case_id: str
    status: Literal["COMPLETED", "PARTIAL", "UNRESOLVED"]
    nodes: list[GraphNode]
    transfers: list[TransferEvidence]
    candidates: list[VaspCandidate]
    limitations: list[str]
    provenance: dict[str, Any]
    manifest_sha256: str
    manifest_payload: dict[str, Any] | None = None
    created_at: datetime
    flow_analysis: FlowAnalysis | None = None
    risk_alerts: list[RiskAlert] = Field(default_factory=list)
    cross_case_alerts: list[CrossCaseAlert] = Field(default_factory=list)
    bridge_observations: list[BridgeObservation] = Field(default_factory=list)
    graph: TraceGraph | None = None


class ChallengeRequest(BaseModel):
    evidence_type: Literal["label", "transaction"]
    evidence_id: str = Field(min_length=4, max_length=160)


class ChallengeResult(BaseModel):
    run_id: str
    evidence_type: Literal["label", "transaction"]
    evidence_id: str
    baseline_candidates: list[VaspCandidate]
    remaining_candidates: list[VaspCandidate]
    conclusion: Literal["STILL_SUPPORTED", "NOW_UNRESOLVED"]
    explanation: str
