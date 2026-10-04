"""Domain types for the Wholesale Broker Channel API.

Entity TypedDicts, status/state enums and the role enum, mirroring the
resource surface described in the PRD.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CHANNEL_MANAGER = "ChannelManager"
    UNDERWRITER = "Underwriter"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    QUALITY_CONTROL_ANALYST = "QualityControlAnalyst"
    BROKER_USER = "BrokerUser"
    ANY = "Any"


class BrokerStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class BrokerTier(str, Enum):
    UNRATED = "UNRATED"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"


class ExclusivityStatus(str, Enum):
    CLEAR = "CLEAR"
    WARNED = "WARNED"
    RESTRICTED = "RESTRICTED"
    BLOCKED = "BLOCKED"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class LicenseType(str, Enum):
    MORTGAGE_BROKER = "MORTGAGE_BROKER"
    MORTGAGE_LENDER = "MORTGAGE_LENDER"
    DUAL_AUTHORITY = "DUAL_AUTHORITY"


class FinancialReviewStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class AttainmentBand(str, Enum):
    MEETS_EXPECTATION = "MEETS_EXPECTATION"
    NEAR_EXPECTATION = "NEAR_EXPECTATION"
    BELOW_EXPECTATION = "BELOW_EXPECTATION"


class ProductCode(str, Enum):
    CONVENTIONAL = "CONVENTIONAL"
    FHA = "FHA"
    VA = "VA"
    JUMBO = "JUMBO"
    USDA = "USDA"


class EligibilityStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REVOKED = "REVOKED"


class PolicyStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    VOIDED = "VOIDED"


class RestrictionScope(str, Enum):
    LOAN_SUBMISSION = "LOAN_SUBMISSION"
    RATE_LOCK = "RATE_LOCK"
    ALL = "ALL"


class SheetStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class OccupancyType(str, Enum):
    PRIMARY_RESIDENCE = "PRIMARY_RESIDENCE"
    SECOND_HOME = "SECOND_HOME"
    INVESTMENT = "INVESTMENT"


class LoanPurpose(str, Enum):
    PURCHASE = "PURCHASE"
    RATE_TERM_REFINANCE = "RATE_TERM_REFINANCE"
    CASH_OUT_REFINANCE = "CASH_OUT_REFINANCE"


class LoanStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDERWRITING = "UNDERWRITING"
    CONDITIONAL_APPROVAL = "CONDITIONAL_APPROVAL"
    SUSPENDED_REVIEW = "SUSPENDED_REVIEW"
    CLEAR_TO_CLOSE = "CLEAR_TO_CLOSE"
    FUNDED = "FUNDED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"
    REPURCHASED = "REPURCHASED"


class ClosingPath(str, Enum):
    ESCALATION_PATH = "ESCALATION_PATH"
    STANDARD_PATH = "STANDARD_PATH"


class CompensationElection(str, Enum):
    LENDER_PAID = "LENDER_PAID"
    BORROWER_PAID = "BORROWER_PAID"
    UNDECIDED = "UNDECIDED"


class PlanCode(str, Enum):
    PLAN_A = "PLAN_A"
    PLAN_B = "PLAN_B"
    PLAN_C = "PLAN_C"


class DecisionType(str, Enum):
    APPROVED = "APPROVED"
    CONDITIONAL = "CONDITIONAL"
    SUSPENDED = "SUSPENDED"
    DENIED = "DENIED"


class EscalationStage(str, Enum):
    UNDERWRITING = "UNDERWRITING"
    CLOSING = "CLOSING"


class EscalationStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class DefectType(str, Enum):
    INCOME_DISCREPANCY = "INCOME_DISCREPANCY"
    UNDISCLOSED_LIABILITY = "UNDISCLOSED_LIABILITY"
    APPRAISAL_DEVIATION = "APPRAISAL_DEVIATION"
    TITLE_DEFECT = "TITLE_DEFECT"
    LICENSE_DEFECT = "LICENSE_DEFECT"
    NON_DEFECT = "NON_DEFECT"


class Severity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class ReviewOutcome(str, Enum):
    PENDING = "PENDING"
    CLEAR = "CLEAR"
    DEFECT = "DEFECT"


class RemediationStatus(str, Enum):
    NONE = "NONE"
    OPEN = "OPEN"
    REMEDIATED = "REMEDIATED"
    VOIDED = "VOIDED"


class ResolutionType(str, Enum):
    REMEDIATED = "REMEDIATED"
    VOIDED = "VOIDED"


# --- Entity shapes -----------------------------------------------------------
# Top-level resources carry id + created_at + updated_at + version.

class Broker(TypedDict):
    id: str
    legal_name: str
    nmls_id: str
    home_state: str
    status: str
    financial_strength_score: float
    tier: str
    licensed_states: List[str]
    approved_product_codes: List[str]
    volume_expectation_cents: int
    rolling_funded_volume_cents: int
    rolling_quality_score: float
    open_defect_tier: int
    exclusivity_status: str
    active_loan_count: int
    total_active_compensation_commitment_cents: int
    suspended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BrokerLicense(TypedDict):
    id: str
    broker_id: str
    state_code: str
    license_number: str
    license_type: str
    expires_on: str
    status: str
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FinancialReview(TypedDict):
    id: str
    broker_id: str
    net_worth_cents: int
    liquidity_cents: int
    total_liabilities_cents: int
    years_in_business: int
    prior_year_funded_volume_cents: int
    audit_attested: bool
    computed_financial_strength_score: float
    status: str
    is_current: bool
    created_at: str
    updated_at: str
    version: int


class ProductEligibility(TypedDict):
    id: str
    broker_id: str
    product_code: str
    max_ltv: float
    min_fico: int
    max_loan_amount_cents: int
    status: str
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExclusivityPolicy(TypedDict):
    id: str
    broker_id: str
    competitor_identifier: str
    competitor_name: str
    effective_from: str
    effective_to: str
    status: str
    breach_count: int
    restriction_scope: str
    created_at: str
    updated_at: str
    version: int


class RateSheet(TypedDict):
    id: str
    broker_id: str
    product_code: str
    base_rate_pct: float
    status: str
    superseded_by_sheet_id: Optional[str]
    published_at: str
    publish_sequence: int
    adjustment_table: list
    created_at: str
    updated_at: str
    version: int


# PricingQuote is an immutable snapshot: id + created_at only.
class PricingQuote(TypedDict):
    id: str
    rate_sheet_id: str
    broker_id: str
    product_code: str
    representative_fico: int
    ltv_ratio: float
    occupancy_type: str
    loan_amount_cents: int
    lock_period_days: int
    loan_purpose: str
    overall_adjustment_pct: float
    note_rate_pct: float
    lock_adjustment_pct: float
    price_points: float
    adjustment_trace: list
    is_repriced: bool
    created_at: str


class LoanSubmission(TypedDict):
    id: str
    broker_id: str
    pricing_quote_id: str
    comp_plan_id: Optional[str]
    borrower_name: str
    property_state: str
    loan_amount_cents: int
    lock_expires_at: str
    competitor_channel_identifier: Optional[str]
    compensation_election: str
    lender_paid_comp_cents: int
    borrower_paid_comp_cents: int
    rate_impact_pct: float
    final_note_rate_pct: float
    defect_remediation_open: bool
    underwriting_due_at: Optional[str]
    closing_due_at: Optional[str]
    repurchase_exposure_cents: int
    status: str
    closing_path: Optional[str]
    submitted_at: Optional[str]
    cleared_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompensationPlan(TypedDict):
    id: str
    broker_id: str
    plan_code: str
    default_election: str
    lender_paid_amount_cents: int
    borrower_paid_amount_cents: int
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class UnderwritingDecision(TypedDict):
    id: str
    loan_submission_id: str
    broker_id: str
    underwriter_id: str
    decision_type: str
    conditions: Optional[List[str]]
    decision_notes: Optional[str]
    decided_at: str
    is_final: bool
    created_at: str
    updated_at: str
    version: int


class TurnTimeEscalation(TypedDict):
    id: str
    loan_submission_id: str
    broker_id: str
    stage: str
    opened_at: str
    target_due_at: str
    resolved_at: Optional[str]
    resolution_note: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityControlReview(TypedDict):
    id: str
    loan_submission_id: str
    broker_id: str
    reviewer_id: str
    defect_type: str
    severity: str
    weighted_defect_points: float
    outcome: str
    remediation_status: str
    repurchase_required: bool
    repurchase_due_at: Optional[str]
    reviewed_at: str
    created_at: str
    updated_at: str
    version: int


class ReconciliationSnapshot(TypedDict):
    total_active_compensation_commitment_cents: int
    rolling_funded_volume_cents: int
    commitment_drift_cents: int
    active_loan_count: int


class ClosingPipelineView(TypedDict):
    escalated_count: int
    standard_count: int
    near_deadline_count: int
    escalated_loan_ids: List[str]
    standard_loan_ids: List[str]


class ClockState(TypedDict):
    current_utc: str
    licenses_expired: int
    escalations_opened: int