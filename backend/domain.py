"""Phase 1 canonical investigation models.

These models deliberately coexist with the v1 API models during migration.  They
are not yet used to change the live tracing response shape.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from .models import Chain


class DataMode(str, Enum):
    LIVE = "LIVE"
    RECORDED_REAL = "RECORDED_REAL"
    SYNTHETIC = "SYNTHETIC"


class SeedType(str, Enum):
    TRANSACTION = "transaction"
    WALLET_CONTEXT = "wallet_context"


class AssertionType(str, Enum):
    VERIFIED = "VERIFIED"
    RULE_INFERRED = "RULE_INFERRED"
    ML_INFERRED = "ML_INFERRED"


class TerminalReason(str, Enum):
    VERIFIED_VASP = "VERIFIED_VASP"
    INFERRED_VASP_DEPOSIT = "INFERRED_VASP_DEPOSIT"
    MIXER_BOUNDARY = "MIXER_BOUNDARY"
    BRIDGE_UNRESOLVED = "BRIDGE_UNRESOLVED"
    DEX_UNRESOLVED = "DEX_UNRESOLVED"
    MAX_HOPS = "MAX_HOPS"
    MAX_NODES = "MAX_NODES"
    TIME_BOUNDARY = "TIME_BOUNDARY"
    AMOUNT_THRESHOLD = "AMOUNT_THRESHOLD"
    NO_OUTGOING = "NO_OUTGOING"
    UNKNOWN = "UNKNOWN"


class HistoricalBalanceQuality(str, Enum):
    EXACT = "EXACT"
    RECONSTRUCTED = "RECONSTRUCTED"
    PARTIAL = "PARTIAL"
    UNKNOWN = "UNKNOWN"


class AllocationPolicyName(str, Enum):
    PROPORTIONAL_HAIRCUT = "proportional_haircut"


class SeedPrecision(str, Enum):
    EXACT = "EXACT"
    APPROXIMATE = "APPROXIMATE"

def normalize_address(chain: Chain, address: str) -> str:
    return address.lower() if chain in {Chain.ETHEREUM, Chain.BNB_CHAIN, Chain.POLYGON} else address


class AssetRef(BaseModel):
    chain: Chain
    symbol: str = Field(min_length=2, max_length=24)
    contract_address: str | None = Field(default=None, min_length=1, max_length=100)
    decimals: int = Field(ge=0, le=36)
    canonical_asset_id: str | None = Field(default=None, max_length=120)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        return value.upper()

    @field_validator("contract_address")
    @classmethod
    def normalize_contract(cls, value: str | None) -> str | None:
        return value.lower() if value and value.startswith("0x") else value


class CaseContextV2(BaseModel):
    """Preferred case input for v2; wallet-context remains a supported fallback."""

    seed_type: SeedType
    chain: Chain
    asset: AssetRef
    disputed_amount: Decimal = Field(gt=0)
    incident_time: datetime
    seed_tx_hash: str | None = Field(default=None, min_length=8, max_length=200)
    seed_wallet: str | None = Field(default=None, min_length=20, max_length=100)
    victim_wallet: str | None = Field(default=None, min_length=20, max_length=100)
    lookback_hours: int | None = Field(default=None, ge=1, le=24 * 30)
    data_mode: DataMode = DataMode.LIVE

    @model_validator(mode="after")
    def validate_seed(self):
        if self.seed_type == SeedType.TRANSACTION and not self.seed_tx_hash:
            raise ValueError("seed_tx_hash is required for transaction-seeded analysis.")
        if self.seed_type == SeedType.WALLET_CONTEXT and not self.seed_wallet:
            raise ValueError("seed_wallet is required for wallet-context analysis.")
        if self.seed_type == SeedType.TRANSACTION and self.lookback_hours is not None:
            raise ValueError("lookback_hours applies only to wallet-context analysis.")
        if self.incident_time.tzinfo is None:
            raise ValueError("incident_time must include a timezone.")
        return self

class CaseCreateV2(BaseModel):
    """Persistent investigation intake for the v2 engine."""

    title: str = Field(min_length=3, max_length=160)
    context: CaseContextV2
    external_case_ref: str | None = Field(default=None, max_length=120)
    trace_policy_id: str = Field(default="v2-default", min_length=3, max_length=80)
    trace_policy: TracePolicyV2 = Field(default_factory=lambda: TracePolicyV2())


class InvestigationCaseV2(BaseModel):
    id: str
    title: str
    context: CaseContextV2
    external_case_ref: str | None = None
    trace_policy_id: str
    trace_policy: TracePolicyV2 = Field(default_factory=lambda: TracePolicyV2())
    status: Literal["OPEN", "UNDER_REVIEW", "CLOSED"] = "OPEN"
    created_at: datetime
    created_by: str

class TracePolicyV2(BaseModel):
    max_hops: int = Field(default=3, ge=1, le=12)
    max_nodes: int = Field(default=100, ge=1, le=10_000)
    max_edges: int = Field(default=500, ge=1, le=50_000)
    min_attributed_amount: Decimal = Field(default=Decimal("0.000001"), ge=0)
    min_attributed_share: Decimal = Field(default=Decimal("0"), ge=0, le=1)
    end_time: datetime | None = None
    max_time_delta_seconds: int | None = Field(default=None, ge=1)
    allocation_policy: AllocationPolicyName = AllocationPolicyName.PROPORTIONAL_HAIRCUT
    stop_on_verified_vasp: bool = True
    stop_on_inferred_vasp_threshold: int | None = Field(default=None, ge=0, le=100)
    continue_through_dex: bool = False
    continue_through_bridge: bool = False
    continue_through_mixer: bool = False
    allowed_assets: list[str] = Field(default_factory=list)


class FlowSeed(BaseModel):
    id: str
    address: str
    asset: AssetRef
    amount: Decimal = Field(gt=0)
    timestamp: datetime
    seed_type: SeedType
    source_transaction_id: str | None = None
    source_evidence_id: str | None = None

    @model_validator(mode="after")
    def normalize_seed_address(self):
        self.address = normalize_address(self.asset.chain, self.address)
        if self.seed_type == SeedType.TRANSACTION and not self.source_transaction_id:
            raise ValueError("Transaction-seeded flow requires source_transaction_id.")
        return self


class WalletAssetStateSnapshot(BaseModel):
    address: str
    asset: AssetRef
    tainted_balance: Decimal = Field(default=Decimal("0"), ge=0)
    clean_balance: Decimal = Field(default=Decimal("0"), ge=0)
    unknown_balance: Decimal = Field(default=Decimal("0"), ge=0)
    historical_balance_quality: HistoricalBalanceQuality


class FlowAllocationV2(BaseModel):
    id: str
    transfer_id: str
    source_address: str
    destination_address: str
    depth: int
    timestamp: datetime
    policy: AllocationPolicyName
    incoming_tainted_balance: Decimal = Field(ge=0)
    incoming_clean_balance: Decimal = Field(ge=0)
    incoming_unknown_balance: Decimal = Field(ge=0)
    transfer_amount: Decimal = Field(ge=0)
    ledger_covered_amount: Decimal = Field(ge=0)
    attributed_disputed_amount: Decimal = Field(ge=0)
    parent_allocation_ids: list[str] = Field(default_factory=list)
    methodology_notes: list[str] = Field(default_factory=list)


class FlowTerminalV2(BaseModel):
    address: str
    amount: Decimal = Field(ge=0)
    reason: TerminalReason
    depth: int
    parent_allocation_ids: list[str] = Field(default_factory=list)
    detail: str


class FundFlowResultV2(BaseModel):
    seed_id: str
    seed_timestamp: datetime
    seed_amount: Decimal
    seed_precision: SeedPrecision
    allocation_policy: AllocationPolicyName
    allocations: list[FlowAllocationV2]
    terminals: list[FlowTerminalV2]
    retained_amount: Decimal = Field(ge=0)
    terminal_amount: Decimal = Field(ge=0)
    unresolved_amount: Decimal = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
    methodology: dict[str, Any]
class EntityType(str, Enum):
    VASP = "VASP"
    BRIDGE = "BRIDGE"
    DEX = "DEX"
    MIXER = "MIXER"
    SERVICE = "SERVICE"
    UNKNOWN = "UNKNOWN"


class EntityRole(str, Enum):
    UNKNOWN = "UNKNOWN"
    PERSONAL_WALLET = "PERSONAL_WALLET"
    VASP_DEPOSIT = "VASP_DEPOSIT"
    VASP_HOT_WALLET = "VASP_HOT_WALLET"
    VASP_COLD_WALLET = "VASP_COLD_WALLET"
    VASP_COLLECTOR = "VASP_COLLECTOR"
    CUSTODIAL_SERVICE = "CUSTODIAL_SERVICE"
    DEX_ROUTER = "DEX_ROUTER"
    DEX_POOL = "DEX_POOL"
    BRIDGE_CONTRACT = "BRIDGE_CONTRACT"
    BRIDGE_RELAYER = "BRIDGE_RELAYER"
    MIXER = "MIXER"
    PAYMENT_PROCESSOR = "PAYMENT_PROCESSOR"
    MERCHANT_SERVICE = "MERCHANT_SERVICE"
    OTHER_SERVICE = "OTHER_SERVICE"


class IntelligenceSourceType(str, Enum):
    GOVERNMENT = "GOVERNMENT"
    VASP_PUBLISHED = "VASP_PUBLISHED"
    REVIEWED_PUBLIC_DATASET = "REVIEWED_PUBLIC_DATASET"
    COMMERCIAL_API = "COMMERCIAL_API"
    COMMUNITY = "COMMUNITY"
    INTERNAL_REVIEW = "INTERNAL_REVIEW"
    RULE_ENGINE = "RULE_ENGINE"
    ML_MODEL = "ML_MODEL"


class TrustTier(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class AssertionReviewState(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    REVIEWED = "REVIEWED"
    REJECTED = "REJECTED"
    STALE = "STALE"


class IntelligenceSourceCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    source_type: IntelligenceSourceType
    source_uri: str | None = Field(default=None, max_length=1000)
    license: str | None = Field(default=None, max_length=500)
    trust_tier: TrustTier
    retrieved_at: datetime
    notes: str | None = Field(default=None, max_length=2000)


class IntelligenceSource(IntelligenceSourceCreate):
    id: str
    created_at: datetime


class EntityCreate(BaseModel):
    canonical_name: str = Field(min_length=2, max_length=160)
    entity_type: EntityType
    jurisdiction: str | None = Field(default=None, max_length=120)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Entity(EntityCreate):
    id: str
    created_at: datetime


class EntityAddressAssertionCreate(BaseModel):
    entity_id: str
    address: str = Field(min_length=20, max_length=100)
    chain: Chain
    role: EntityRole
    assertion_type: AssertionType
    source_id: str
    review_state: AssertionReviewState = AssertionReviewState.UNREVIEWED
    first_verified_at: datetime | None = None
    last_verified_at: datetime | None = None
    stale_after: datetime | None = None
    evidence_score: int | None = Field(default=None, ge=0, le=100)
    evidence_components: dict[str, int] = Field(default_factory=dict)
    notes: str | None = Field(default=None, max_length=3000)
    risk_tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_assertion_address(self):
        self.address = normalize_address(self.chain, self.address)
        if self.last_verified_at and self.first_verified_at and self.last_verified_at < self.first_verified_at:
            raise ValueError("last_verified_at cannot be earlier than first_verified_at.")
        return self


class EntityAddressAssertion(EntityAddressAssertionCreate):
    id: str
    evidence_hash_sha256: str
    created_at: datetime


class ResolvedEntityAssertion(BaseModel):
    assertion: EntityAddressAssertion
    entity: Entity
    source: IntelligenceSource
    effective_review_state: AssertionReviewState
    warnings: list[str] = Field(default_factory=list)
class CandidateStatus(str, Enum):
    VERIFIED = "VERIFIED"
    INFERRED_STRONG = "INFERRED_STRONG"
    INFERRED_WEAK = "INFERRED_WEAK"
    UNRESOLVED = "UNRESOLVED"


class EvidenceBand(str, Enum):
    STRONG = "STRONG"
    MODERATE = "MODERATE"
    WEAK = "WEAK"


class AttributionEvidenceComponents(BaseModel):
    exact_reviewed_label: int = Field(ge=0, le=40)
    cluster_relationship: int = Field(ge=0, le=25)
    deposit_behavior: int = Field(ge=0, le=20)
    independent_corroboration: int = Field(ge=0, le=10)
    freshness: int = Field(ge=0, le=5)

    @property
    def total(self) -> int:
        return sum((self.exact_reviewed_label, self.cluster_relationship, self.deposit_behavior, self.independent_corroboration, self.freshness))


class AttributionCandidateV2(BaseModel):
    id: str
    entity_id: str
    entity_name: str
    terminal_addresses: list[str]
    terminal_roles: list[EntityRole]
    status: CandidateStatus
    min_hops: int
    attributed_amount: Decimal = Field(ge=0)
    disputed_share: Decimal = Field(ge=0, le=1)
    first_arrival: datetime | None = None
    latest_arrival: datetime | None = None
    path_ids: list[str]
    evidence_ids: list[str]
    attribution_evidence: AttributionEvidenceComponents
    attribution_evidence_score: int = Field(ge=0, le=100)
    attribution_band: EvidenceBand
    materiality: dict[str, Any]


class AttributionSummaryV2(BaseModel):
    candidates: list[AttributionCandidateV2]
    nearest_actionable_candidate_id: str | None = None
    largest_material_candidate_id: str | None = None
    unresolved_amount: Decimal = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
class DepositInferenceResult(BaseModel):
    id: str
    address: str
    asset: AssetRef
    candidate_entity_id: str
    candidate_entity_name: str
    inferred_role: EntityRole = EntityRole.VASP_DEPOSIT
    assertion_type: AssertionType = AssertionType.RULE_INFERRED
    evidence_score: int = Field(ge=0, le=100)
    evidence_components: dict[str, int]
    feature_snapshot: dict[str, Any]
    reasons: list[str]
    evidence_lineage_ids: list[str]
    inference_depth: int = Field(ge=0)
    created_at: datetime
class RawEvidenceArtifact(BaseModel):
    id: str
    kind: Literal["provider_response_metadata", "provider_response", "label_source", "rule_explanation", "ml_feature_snapshot"]
    provider: str
    retrieved_at: datetime
    content_hash_sha256: str | None = Field(default=None, min_length=64, max_length=64)
    request_fingerprint: str | None = Field(default=None, min_length=64, max_length=64)
    source_uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class InvestigationTraceRequestV2(BaseModel):
    """Run input for a v2 case with an explicit evidence boundary."""

    trace_policy: TracePolicyV2 | None = None
    max_transfers_per_wallet: int = Field(default=100, ge=1, le=1_000)
    seed_transfer_id: str | None = Field(default=None, min_length=3, max_length=200)
    recorded_transfers: list[CanonicalTransfer] = Field(default_factory=list)
    recorded_evidence: list[RawEvidenceArtifact] = Field(default_factory=list)


class RecordedTraceImportV2(BaseModel):
    """A replay package carried entirely by the investigator, with no hidden provider calls."""

    case: CaseCreateV2
    trace: InvestigationTraceRequestV2

    @model_validator(mode="after")
    def validate_recorded_mode(self):
        if self.case.context.data_mode not in {DataMode.RECORDED_REAL, DataMode.SYNTHETIC}:
            raise ValueError("Recorded import requires a RECORDED_REAL or SYNTHETIC case data mode.")
        if not self.trace.recorded_transfers:
            raise ValueError("Recorded import requires at least one canonical transfer.")
        return self


class RecordedTraceCsvImportV2(BaseModel):
    case: CaseCreateV2
    transfers_csv: str = Field(min_length=50, max_length=5_000_000)
    recorded_evidence: list[RawEvidenceArtifact] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_recorded_mode(self):
        if self.case.context.data_mode not in {DataMode.RECORDED_REAL, DataMode.SYNTHETIC}:
            raise ValueError("CSV replay requires a RECORDED_REAL or SYNTHETIC case data mode.")
        return self

class EntityRelationshipType(str, Enum):
    CLUSTER_MEMBER_OF = "CLUSTER_MEMBER_OF"
    OPERATED_BY = "OPERATED_BY"
    RELATED_SERVICE = "RELATED_SERVICE"


class EntityRelationshipCreate(BaseModel):
    source_entity_id: str
    target_entity_id: str
    relationship_type: EntityRelationshipType
    source_id: str
    review_state: AssertionReviewState = AssertionReviewState.UNREVIEWED
    notes: str | None = Field(default=None, max_length=3_000)

    @model_validator(mode="after")
    def validate_distinct_entities(self):
        if self.source_entity_id == self.target_entity_id:
            raise ValueError("Entity relationships must connect two distinct entities.")
        return self


class EntityRelationship(EntityRelationshipCreate):
    id: str
    evidence_hash_sha256: str
    created_at: datetime

class AssertionReviewV2(BaseModel):
    review_state: Literal["REVIEWED", "REJECTED"]
    rationale: str = Field(min_length=3, max_length=3_000)


class AssertionReviewEventV2(BaseModel):
    id: str
    assertion_id: str
    reviewer: str
    review_state: AssertionReviewState
    rationale: str
    created_at: datetime

class CanonicalTransaction(BaseModel):
    id: str
    chain: Chain
    tx_hash: str
    block_number: int | None = None
    block_hash: str | None = None
    timestamp: datetime
    confirmed: bool
    raw_evidence_id: str

    @field_validator("tx_hash")
    @classmethod
    def normalize_hash(cls, value: str) -> str:
        return value.lower()


class CanonicalTransfer(BaseModel):
    id: str
    transaction_id: str
    chain: Chain
    source_address: str
    destination_address: str
    asset: AssetRef
    raw_amount: Decimal = Field(ge=0)
    normalized_amount: Decimal = Field(ge=0)
    timestamp: datetime
    transfer_type: Literal["native", "token", "internal", "utxo", "synthetic_bridge_edge"] = "token"
    log_index: int | None = Field(default=None, ge=0)
    event_index: int | None = Field(default=None, ge=0)
    raw_evidence_id: str

    @model_validator(mode="after")
    def normalize_addresses(self):
        self.source_address = normalize_address(self.chain, self.source_address)
        self.destination_address = normalize_address(self.chain, self.destination_address)
        return self


class ProviderAdapterResult(BaseModel):
    provider: str
    chain: Chain
    transfers: list[CanonicalTransfer]
    evidence: RawEvidenceArtifact
    complete: bool
    warnings: list[str] = Field(default_factory=list)


class EvidenceManifestEntry(BaseModel):
    """A hashed reference retained by an immutable investigation result."""

    id: str
    kind: str
    provider: str
    sha256: str = Field(min_length=64, max_length=64)
    retrieved_at: datetime | None = None
    source_uri: str | None = None


class EvidenceManifestV2(BaseModel):
    case_id: str
    result_version: int = Field(ge=1)
    generated_at: datetime
    algorithm_versions: dict[str, str]
    evidence: list[EvidenceManifestEntry]
    sha256: str = Field(min_length=64, max_length=64)


class InvestigationResultV2(BaseModel):
    """Immutable, versioned evidence snapshot for every downstream output."""

    id: str
    case_id: str
    version: int = Field(ge=1)
    generated_at: datetime
    trace_fingerprint: str = Field(min_length=64, max_length=64)
    data_mode: DataMode
    trace_engine_version: str
    entity_resolver_version: str
    attribution_engine_version: str
    flow: FundFlowResultV2
    transfers: list[CanonicalTransfer] = Field(default_factory=list)
    attribution: AttributionSummaryV2
    deposit_inferences: list[DepositInferenceResult] = Field(default_factory=list)
    evidence_manifest: EvidenceManifestV2
    limitations: list[str] = Field(default_factory=list)
    methodology: dict[str, Any] = Field(default_factory=dict)


class RequestDraftV2(BaseModel):
    """Local export only. It never represents an external SAHYOG submission."""

    id: str
    case_id: str
    result_id: str
    result_version: int
    vasp_entity_id: str
    vasp_entity_name: str
    terminal_addresses: list[str]
    terminal_roles: list[EntityRole]
    relevant_transfer_ids: list[str]
    relevant_transaction_ids: list[str]
    attributed_amount: Decimal = Field(ge=0)
    chain: Chain
    asset: AssetRef
    evidence_manifest_sha256: str = Field(min_length=64, max_length=64)
    evidence_ids: list[str]
    request_purpose: str
    investigator_notes: str
    status: Literal["LOCAL_DRAFT_REQUIRES_AUTHORIZED_REVIEW"] = "LOCAL_DRAFT_REQUIRES_AUTHORIZED_REVIEW"
    created_at: datetime
    boundary_notice: str

class CaseStatusUpdateV2(BaseModel):
    status: Literal["OPEN", "UNDER_REVIEW", "CLOSED"]

class MLLabelTier(str, Enum):
    REVIEWED_GROUND_TRUTH = "REVIEWED_GROUND_TRUTH"
    WEAK = "WEAK"
    UNLABELED = "UNLABELED"


class WalletRoleClass(str, Enum):
    DEPOSIT_LIKE = "DEPOSIT_LIKE"
    SERVICE_LIKE = "SERVICE_LIKE"
    ORDINARY = "ORDINARY"
    UNKNOWN = "UNKNOWN"


class MLInferenceStatus(str, Enum):
    STRONG = "STRONG"
    WEAK = "WEAK"
    WITHHELD = "WITHHELD"


class FeatureSnapshotV2(BaseModel):
    id: str
    address: str
    chain: Chain
    asset: AssetRef
    snapshot_time: datetime
    feature_schema_version: str
    features: dict[str, float | None]
    evidence_ids: list[str]
    source_block_start: int | None = None
    source_block_end: int | None = None
    feature_hash_sha256: str = Field(min_length=64, max_length=64)
    created_at: datetime


class TrainingRowV2(BaseModel):
    feature_snapshot_id: str
    snapshot_time: datetime
    label: WalletRoleClass
    label_tier: MLLabelTier
    entity_id: str | None = None
    cluster_id: str | None = None
    label_assertion_id: str | None = None
    label_source_id: str | None = None
    feature_hash_sha256: str = Field(min_length=64, max_length=64)


class TrainingDatasetV2(BaseModel):
    id: str
    version: str
    task: Literal["wallet_role_classifier", "vasp_pair_association"]
    rows: list[TrainingRowV2]
    reviewed_row_count: int = Field(ge=0)
    weak_row_count: int = Field(ge=0)
    excluded_unlabeled_count: int = Field(ge=0)
    created_at: datetime
    dataset_hash_sha256: str = Field(min_length=64, max_length=64)


class ModelVersionV2(BaseModel):
    id: str
    model_name: str
    version: str
    task: Literal["wallet_role_classifier", "vasp_pair_association"]
    artifact_uri: str
    artifact_sha256: str = Field(min_length=64, max_length=64)
    artifact: dict[str, Any]
    feature_schema_version: str
    training_dataset_version: str
    trained_at: datetime
    evaluation_metrics: dict[str, Any]
    threshold_config: dict[str, float]
    enabled: bool = False
    notes: str | None = None


class ModelInferenceV2(BaseModel):
    id: str
    model_version_id: str
    feature_snapshot_id: str
    task: Literal["wallet_role_classifier", "vasp_pair_association"]
    assertion_type: Literal["ML_INFERRED"] = "ML_INFERRED"
    status: MLInferenceStatus
    predicted_role: WalletRoleClass | None = None
    candidate_entity_id: str | None = None
    raw_score: float = Field(ge=0, le=1)
    threshold_applied: float = Field(ge=0, le=1)
    top_contributing_features: list[str] = Field(default_factory=list)
    explanation: str
    created_at: datetime


class MLFeatureSnapshotRequest(BaseModel):
    address: str = Field(min_length=20, max_length=100)
    asset: AssetRef
    snapshot_time: datetime
    lookback_hours: int | None = Field(default=None, ge=1, le=24 * 365)
    transfers: list[CanonicalTransfer]


class MLInferenceRequest(BaseModel):
    feature_snapshot_id: str


class PairAssociationFeatureV2(BaseModel):
    address: str
    candidate_entity_id: str
    snapshot_time: datetime
    features: dict[str, float | None]
    evidence_ids: list[str]

class MLDatasetBuildRequest(BaseModel):
    feature_snapshot_ids: list[str] = Field(min_length=1, max_length=10_000)


class MLRoleTrainingRequest(BaseModel):
    dataset_id: str


class MLPairAssociationRequest(BaseModel):
    address: str = Field(min_length=20, max_length=100)
    candidate_entity_id: str
    asset: AssetRef
    snapshot_time: datetime
    transfers: list[CanonicalTransfer]