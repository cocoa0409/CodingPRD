"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    CONSUMER = "Consumer"
    REFEREE = "Referee"
    BUREAU_CONNECTOR = "BureauConnector"
    LENDER_OPS = "LenderOps"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"
    DATA_PROTECTION_OFFICER = "DataProtectionOfficer"


class MonitoringPosture(str, Enum):
    ENROLLED = "ENROLLED"
    MONITORING = "MONITORING"
    COMPLETE = "COMPLETE"
    IMMATURE = "IMMATURE"


class BureauSnapshotStatus(str, Enum):
    PULL_REQUESTED = "PULL_REQUESTED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class ScoreAlertKind(str, Enum):
    SCORE_UP = "SCORE_UP"
    SCORE_DOWN = "SCORE_DOWN"
    SCORE_FLAT = "SCORE_FLAT"


class ScoreAlertStatus(str, Enum):
    PENDING = "PENDING"
    DELIVERED = "DELIVERED"
    SUPPRESSED = "SUPPRESSED"


class ScoreSimulationStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    FAILED = "FAILED"


class ProductKind(str, Enum):
    CARD = "CARD"
    LOAN = "LOAN"
    INSURANCE = "INSURANCE"


class ProductCatalogItemStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class LenderComplianceStatus(str, Enum):
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    BANNED = "BANNED"


class LenderStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    OFFBOARDED = "OFFBOARDED"


class LenderProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    EXPIRED = "EXPIRED"


class CriterionField(str, Enum):
    SCORE = "SCORE"
    DTI_PCT = "DTI_PCT"
    UTILIZATION_PCT = "UTILIZATION_PCT"
    STATE_CODE = "STATE_CODE"


class CriterionOperator(str, Enum):
    GTE = "GTE"
    LTE = "LTE"
    EQ = "EQ"
    IN = "IN"


class DecisionStatus(str, Enum):
    NEEDS_SNAPSHOT = "NEEDS_SNAPSHOT"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    PREQUALIFIED = "PREQUALIFIED"
    CONSENTED = "CONSENTED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"


class ConsentScope(str, Enum):
    SHARE_PII_WITH_LENDER = "SHARE_PII_WITH_LENDER"


class ConsentMethod(str, Enum):
    ELECTRONIC = "ELECTRONIC"
    WRITTEN = "WRITTEN"


class ConsentRecordStatus(str, Enum):
    PENDING = "PENDING"
    SEALED = "SEALED"
    NOT_SEALED = "NOT_SEALED"


class ArchiveStatus(str, Enum):
    LIVE = "LIVE"
    ARCHIVED = "ARCHIVED"


class ReferralStatus(str, Enum):
    SENT = "SENT"
    FUNDED = "FUNDED"
    REVERSED = "REVERSED"
    DECLINED = "DECLINED"
    UNFUNDED = "UNFUNDED"


class DisputeStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED_OFFLINE = "SUBMITTED_OFFLINE"
    ACKNOWLEDGED_BY_BUREAU = "ACKNOWLEDGED_BY_BUREAU"
    WITHDRAWN = "WITHDRAWN"


class InaccuracyType(str, Enum):
    PERSONAL_INFO = "PERSONAL_INFO"
    ACCOUNT_INFO = "ACCOUNT_INFO"
    INQUIRY = "INQUIRY"
    BALANCE = "BALANCE"


class RevenueEntryKind(str, Enum):
    REVENUE = "REVENUE"
    CLAWBACK = "CLAWBACK"


class ScoreTierCode(str, Enum):
    EXCEPTIONAL = "EXCEPTIONAL"
    VERY_GOOD = "VERY_GOOD"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"


class OfferStatus(str, Enum):
    PRESENTED = "PRESENTED"
    RENDERED = "RENDERED"
    CONSUMED = "CONSUMED"
    WITHDRAWN = "WITHDRAWN"
    STALE = "STALE"


class RenderPosture(str, Enum):
    RENDER_OPEN = "RENDER_OPEN"
    RENDER_FACETS_INCOMPLETE = "RENDER_FACETS_INCOMPLETE"
    RENDER_RESTRICTED = "RENDER_RESTRICTED"


class ContentTopic(str, Enum):
    FACTOR_EXPLANATIONS = "factor_explanations"
    ACCURACY_EDUCATION = "accuracy_education"


class FacetStatus(str, Enum):
    COMPLETE = "COMPLETE"
    INCOMPLETE = "INCOMPLETE"


class OpsRunStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"


class SimActionCode(str, Enum):
    PAY_DOWN_REVOLVING = "PAY_DOWN_REVOLVING"
    CLOSE_OLDEST_TRADELINE = "CLOSE_OLDEST_TRADELINE"
    INCREASE_CREDIT_LIMIT = "INCREASE_CREDIT_LIMIT"
    OPEN_NEW_TRADELINE = "OPEN_NEW_TRADELINE"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# common_fields: true — id + created_at + updated_at + version
# ---------------------------------------------------------------------------

class Consumer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    state_code: str
    dti_pct: float
    bureau_pin: str
    monitoring_consent_at: Optional[str]
    score_version: int
    current_score: Optional[int]
    previous_score: Optional[int]
    utilization_pct: Optional[float]
    open_dispute_count: int
    created_at: str
    updated_at: str
    version: int


class BureauSnapshot(TypedDict, total=False):
    id: str
    consumer_id: str
    snapshot_ordinal: int
    pulled_at: str
    score: int
    added_account_count: int
    total_revolving_balance_cents: int
    credit_limit_total_cents: int
    overall_credit_utilization_pct: float
    factor_codes: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ScoreAlert(TypedDict, total=False):
    id: str
    consumer_id: str
    alert_kind: str
    threshold_used: int
    from_score: int
    to_score: int
    channel: str
    status: str
    evaluated_at: str
    created_at: str
    updated_at: str
    version: int


class ScoreSimulation(TypedDict, total=False):
    id: str
    consumer_id: str
    baseline_ordinal: int
    baseline_score: int
    base_utilization_pct: float
    actions: List[dict]
    projected_score: Optional[int]
    delta_points: Optional[int]
    tier_code: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductCatalogItem(TypedDict, total=False):
    id: str
    product_kind: str
    product_name: str
    min_score: int
    max_score: int
    max_dti_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Lender(TypedDict, total=False):
    id: str
    lender_name: str
    compliance_status: str
    states_served: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LenderProgram(TypedDict, total=False):
    id: str
    lender_id: str
    product_catalog_item_id: str
    program_name: str
    program_code: str
    min_modeled_score: int
    max_dti_pct: float
    max_eligible_utilization_pct: float
    annual_fee_cents: int
    intro_apr_bps: int
    go_live_at: str
    expiry_at: str
    revenue_share_bps: int
    clawback_rate_bps: int
    clawback_days: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TargetingCriterion(TypedDict, total=False):
    id: str
    lender_program_id: str
    criterion_field: str
    operator: str
    criterion_value: str
    is_hard_requirement: bool
    created_at: str
    updated_at: str
    version: int


class PreQualificationDecision(TypedDict, total=False):
    id: str
    consumer_id: str
    lender_program_id: str
    snapshot_id: str
    snapshot_ordinal_used: int
    modeled_odds_pct: Optional[float]
    modeled_odds_settled: bool
    decision_status: str
    disqualifying_criteria: List[dict]
    reason: str
    decided_at: str
    fresh_until: str
    created_at: str
    updated_at: str
    version: int


class PreQualifiedOffer(TypedDict, total=False):
    id: str
    decision_id: str
    consumer_id: str
    lender_program_id: str
    product_kind: str
    channel: str
    intent_recorded_at: str
    render_intent_recorded_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict, total=False):
    id: str
    consumer_id: str
    decision_id: str
    external_referral_ref: str
    channel: str
    revenue_share_bps: int
    clawback_days: int
    status: str
    funded_amount_cents: Optional[int]
    funded_at: Optional[str]
    reversed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DisputeReferral(TypedDict, total=False):
    id: str
    consumer_id: str
    snapshot_id: str
    referral_id: Optional[str]
    referral_count: int
    inaccuracy_type: str
    narrative: str
    bureau_case_ref: Optional[str]
    education_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ScoreTierThreshold(TypedDict, total=False):
    id: str
    tier_code: str
    min_score: int
    max_score: int
    factor_catalog: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ScoreAlertThreshold(TypedDict, total=False):
    id: str
    consumer_id: str
    threshold_override_points: int
    created_at: str
    updated_at: str
    version: int


class RenderPolicy(TypedDict, total=False):
    id: str
    consumer_id: str
    blanket_presentation_override: bool
    content_quality_override: bool
    render_posture: str
    created_at: str
    updated_at: str
    version: int


class ContentQualityFacet(TypedDict, total=False):
    id: str
    consumer_id: str
    topic: str
    score_bps: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OfferPresentationCap(TypedDict, total=False):
    id: str
    consumer_id: str
    product_kind: str
    presented_count: int
    presentation_cap_bps: int
    created_at: str
    updated_at: str
    version: int


class OpsRun(TypedDict, total=False):
    id: str
    run_key: str
    status: str
    stages_passed: List[str]
    requested_at: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only families — only id and created_at (no updated_at, no version)
# ---------------------------------------------------------------------------

class ScoreFactorExplanation(TypedDict, total=False):
    id: str
    snapshot_id: str
    factor_code: str
    direction: str
    impact_points: int
    rank_index: int
    created_at: str


class ConsentRecord(TypedDict, total=False):
    id: str
    consumer_id: str
    decision_id: str
    consent_method: str
    consent_scope: str
    consumer_pii_ciphertext: Optional[str]
    lender_routing_netloc: Optional[str]
    status: str
    consented_at: str
    sealed_at: Optional[str]
    archive_status: str
    created_at: str


class RevenueRecognitionEntry(TypedDict, total=False):
    id: str
    consumer_id: str
    referral_id: str
    entry_kind: str
    realized_amount_cents: int
    recognized_at: str
    created_at: str