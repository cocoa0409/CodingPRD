"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity surfaces and lifecycle declarations.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ─── Enumerations ─────────────────────────────────────

class BureauCode(str, Enum):
    TUC = "TUC"
    EXP = "EXP"
    EQF = "EQF"


class FamilyCode(str, Enum):
    FICO_CORE = "FICO_CORE"
    VANTAGE_STYLE = "VANTAGE_STYLE"


class ScoreModelStatus(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"
    RELEASED = "RELEASED"
    DEPRECATED = "DEPRECATED"
    RETIRED = "RETIRED"
    SUPERSEDED = "SUPERSEDED"


class Industry(str, Enum):
    AUTO = "AUTO"
    BANKCARD = "BANKCARD"
    MORTGAGE = "MORTGAGE"
    PERSONAL_LOAN = "PERSONAL_LOAN"


class ScoreVariantStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    RECALLED = "RECALLED"


class SegmentName(str, Enum):
    PRIME = "PRIME"
    NEAR_PRIME = "NEAR_PRIME"
    SUBPRIME = "SUBPRIME"
    THIN_FILE = "THIN_FILE"


class SampleKind(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"
    VALIDATION = "VALIDATION"


class StudyPath(str, Enum):
    PROTECTED_CLASS = "PROTECTED_CLASS"
    CROSS_BUREAU = "CROSS_BUREAU"


class StudyStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    VALIDATION_COMPLETE = "VALIDATION_COMPLETE"
    BLOCKED = "BLOCKED"
    COMPENSATED = "COMPENSATED"


class ReferenceSetStatus(str, Enum):
    COMPILED = "COMPILED"
    BOUND = "BOUND"
    RECONCILED = "RECONCILED"


class ScoreDecision(str, Enum):
    APPROVE = "APPROVE"
    DECLINE = "DECLINE"
    UNDECIDED = "UNDECIDED"


class DepthTier(str, Enum):
    PRIMARY = "PRIMARY"
    SECONDARY = "SECONDARY"
    TERTIARY = "TERTIARY"


class ReasonCodeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class VolumeTier(str, Enum):
    VOLUME_TIER_1 = "VOLUME_TIER_1"
    VOLUME_TIER_2 = "VOLUME_TIER_2"
    VOLUME_TIER_3 = "VOLUME_TIER_3"


class LicenseStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class EntitlementStatus(str, Enum):
    NOT_SET = "NOT_SET"
    WITHIN_ENTITLEMENT = "WITHIN_ENTITLEMENT"
    OVER_ENTITLED = "OVER_ENTITLED"


class FeeLedgerKind(str, Enum):
    MARGINAL_PRICING = "MARGINAL_PRICING"
    VOID_REVERSAL = "VOID_REVERSAL"


class DocumentationType(str, Enum):
    MODEL_RISK_REPORT = "MODEL_RISK_REPORT"
    FAIR_LENDING_REPORT = "FAIR_LENDING_REPORT"
    ADVERSE_ACTION_MAP = "ADVERSE_ACTION_MAP"
    BUREAU_DISCREPANCY_REPORT = "BUREAU_DISCREPANCY_REPORT"


class DocumentationStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    SUPPLEMENTED = "SUPPLEMENTED"


class MigrationEventType(str, Enum):
    RECALIBRATED = "RECALIBRATED"
    SNAPSHOT_COMPILED = "SNAPSHOT_COMPILED"
    MIGRATED = "MIGRATED"


class DiscoveryRequestStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


class UserRole(str, Enum):
    BUREAU_ADMINISTRATOR = "BureauAdministrator"
    MODEL_DEVELOPER = "ModelDeveloper"
    VALIDATION_ANALYST = "ValidationAnalyst"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    FAIR_LENDING_OFFICER = "FairLendingOfficer"
    REASON_CODE_ADMINISTRATOR = "ReasonCodeAdministrator"
    SCORE_CONSUMER = "ScoreConsumer"


# ─── Entity shapes ────────────────────────────────────
# Every primary resource carries id + created_at + updated_at + version.

class Bureau(TypedDict):
    id: str
    bureau_code: str
    display_name: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class ScoreModel(TypedDict):
    id: str
    family_code: str
    version_label: str
    predecessor_model_id: Optional[str]
    status: str
    released_at: Optional[str]
    retired_at: Optional[str]
    min_input_count: int
    score_floor: int
    score_ceiling: int
    active_variant_count: int
    cascade_depth: int
    created_at: str
    updated_at: str
    version: int


class ScoreVariant(TypedDict):
    id: str
    score_model_id: str
    industry: str
    ref_score: int
    base_odds: float
    double_odds_points: int
    segment_width: int
    segment_offsets: List[int]
    rounding_penalty_pct: float
    aggregate_weight_pct: float
    elongation_points: int
    cutoff_baseline: int
    status: str
    distribution_shift_points: float
    validated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Consumer(TypedDict):
    id: str
    consumer_ref: str
    age_years: int
    is_protected_class: bool
    model_undecided_count: int
    latest_uploaded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ArchiveSample(TypedDict):
    id: str
    score_model_id: str
    sample_ref: str
    record_count: int
    segment_name: str
    sample_kind: str
    window_start_month: str
    window_end_month: str
    observation_window_months: int
    created_at: str
    updated_at: str
    version: int


class ValidationStudy(TypedDict):
    id: str
    score_model_id: str
    sample_id: str
    study_path: str
    status: str
    touched_model_ids: List[str]
    disparate_impact_ratio_ppm: Optional[int]
    reconciliation_variance: Optional[float]
    performed_by: str
    finalized_by: Optional[str]
    evidence_ref: Optional[str]
    model_doc_id: Optional[str]
    required_reason_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class ReferenceSet(TypedDict):
    id: str
    consumer_id: str
    score_model_id: str
    reason_code_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ScoreResult(TypedDict):
    id: str
    consumer_id: str
    score_variant_id: str
    bureau_id: str
    reference_set_id: Optional[str]
    license_id: str
    raw_posted_score: int
    effective_score: int
    odds_at_posted_score: float
    decision: Optional[str]
    decision_reason_code_id: Optional[str]
    migration_event_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReasonCode(TypedDict):
    id: str
    score_variant_id: str
    depth_tier: str
    trigger_feature_code: str
    code_label: str
    composite_code: str
    weight_pct: float
    weight_received_pct: float
    weight_effective_pct: float
    parent_reason_code_id: Optional[str]
    status: str
    bind_count: int
    created_at: str
    updated_at: str
    version: int


class License(TypedDict):
    id: str
    lender_name: str
    lender_code: str
    score_variant_id: str
    volume_tier: str
    entitled_count: int
    status: str
    entitlement_status: str
    cumulative_score_count: int
    cumulative_fee_cents: int
    window_start_month: str
    window_end_month: str
    window_credited_delta_bps: int
    window_outcome_mixture_ratio_ppm: int
    created_at: str
    updated_at: str
    version: int


class ModelDocumentation(TypedDict):
    id: str
    score_model_id: str
    study_id: Optional[str]
    doc_type: str
    required_version_label: str
    status: str
    filed_at: Optional[str]
    checksum: str
    created_at: str
    updated_at: str
    version: int


class ScoreDiscoveryRequest(TypedDict):
    id: str
    tag: str
    requested_at: str
    status: str
    consumed_score_result_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


# ─── Append-only ledger rows ──────────────────────────
# These carry ONLY id and created_at; no updated_at, no version.

class FeeLedgerEntry(TypedDict):
    id: str
    license_id: str
    score_result_id: Optional[str]
    kind: str
    cumulative_count_before: int
    fee_cents: int
    ledger_description: str
    created_at: str


class MigrationEvent(TypedDict):
    id: str
    lender_code: str
    from_score_variant_id: str
    to_score_variant_id: str
    event_type: str
    evidence_ref: str
    carried_decision_reason_code_id: Optional[str]
    credited_delta_bps: int
    voided_at: Optional[str]
    created_at: str