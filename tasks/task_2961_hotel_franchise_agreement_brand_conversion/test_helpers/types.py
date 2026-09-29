"""Domain types for the Hotel Franchise Conversion API.

Entity TypedDicts, the seventeen state-axis enumerations, the enumerated
vocabularies and the four recognised roles, all named exactly as the PRD
names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ────────────────────────────────────────────────

class UserRole(str, Enum):
    FRANCHISE_DEVELOPMENT_MANAGER = "FranchiseDevelopmentManager"
    BRAND_STANDARDS_DIRECTOR = "BrandStandardsDirector"
    QA_INSPECTOR = "QaInspector"
    OWNER = "Owner"


# ─── State axes (PRD §2.8) ───────────────────────────────────────────

class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"


class FinancialReviewStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    STALE = "STALE"


class ImpactStudyStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PRELIMINARY = "PRELIMINARY"
    FINAL = "FINAL"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    SUSTAINED = "SUSTAINED"
    OVERRULED = "OVERRULED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    OPEN = "OPEN"
    TERMINATION_PENDING = "TERMINATION_PENDING"
    TERMINATED = "TERMINATED"
    VOIDED = "VOIDED"


class ComplianceStatus(str, Enum):
    COMPLIANT = "COMPLIANT"
    CURE_PERIOD = "CURE_PERIOD"
    DEFAULT_NOTICE = "DEFAULT_NOTICE"
    TERMINATION_ELIGIBLE = "TERMINATION_ELIGIBLE"


class TrainingStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    COMPLETED = "COMPLETED"


class SystemsStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    PROVISIONED = "PROVISIONED"
    VALIDATED = "VALIDATED"


class ChannelStatus(str, Enum):
    NOT_CONNECTED = "NOT_CONNECTED"
    TESTING = "TESTING"
    CONNECTED = "CONNECTED"
    SUSPENDED = "SUSPENDED"


class DeIdentificationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    BREACHED = "BREACHED"
    VERIFIED = "VERIFIED"


class PostTerminationStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class PipStatus(str, Enum):
    SCOPED = "SCOPED"
    ACCEPTED = "ACCEPTED"
    IN_PROGRESS = "IN_PROGRESS"
    DEFAULTED = "DEFAULTED"
    COMPLETED = "COMPLETED"
    SUSPENDED = "SUSPENDED"


class PipItemStatus(str, Enum):
    PENDING = "PENDING"
    SUBMITTED = "SUBMITTED"
    OVERDUE = "OVERDUE"
    VERIFIED = "VERIFIED"


class ExtensionStatus(str, Enum):
    NONE = "NONE"
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class InspectionStatus(str, Enum):
    CLOSED = "CLOSED"
    CURE_PENDING = "CURE_PENDING"
    CURE_SUBMITTED = "CURE_SUBMITTED"
    CURE_PASSED = "CURE_PASSED"
    CURE_FAILED = "CURE_FAILED"


class TransferRequestStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CONSENTED = "CONSENTED"
    REFUSED = "REFUSED"


class ExistingUnitStatus(str, Enum):
    OPERATING = "OPERATING"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class OwnerStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"


# ─── Enumerated vocabularies (PRD §2.12) ─────────────────────────────

class BrandTier(str, Enum):
    ECONOMY = "ECONOMY"
    MIDSCALE = "MIDSCALE"
    UPSCALE = "UPSCALE"
    LUXURY = "LUXURY"


class CapacityBand(str, Enum):
    STRONG = "STRONG"
    ADEQUATE = "ADEQUATE"
    INSUFFICIENT = "INSUFFICIENT"


class CapacityBasis(str, Enum):
    STANDALONE = "STANDALONE"
    PORTFOLIO_ADJUSTED = "PORTFOLIO_ADJUSTED"


class CurrentAffiliation(str, Enum):
    INDEPENDENT = "INDEPENDENT"
    COMPETITOR = "COMPETITOR"
    OUR_BRAND = "OUR_BRAND"


class EncroachmentVerdict(str, Enum):
    CLEAR = "CLEAR"
    MITIGATION_REQUIRED = "MITIGATION_REQUIRED"
    ENCROACHMENT_CONFIRMED = "ENCROACHMENT_CONFIRMED"


class DecisionOutcome(str, Enum):
    APPROVE = "APPROVE"
    DECLINE = "DECLINE"


class PipItemCategory(str, Enum):
    GUESTROOM = "GUESTROOM"
    EXTERIOR = "EXTERIOR"
    FOOD_BEVERAGE = "FOOD_BEVERAGE"
    LIFE_SAFETY = "LIFE_SAFETY"
    TECHNOLOGY = "TECHNOLOGY"


class PipItemPriority(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class InspectionGrade(str, Enum):
    PASS = "PASS"
    CONDITIONAL = "CONDITIONAL"
    FAIL = "FAIL"


class RequestType(str, Enum):
    TRANSFER = "TRANSFER"
    CHANGE_OF_CONTROL = "CHANGE_OF_CONTROL"
    REFINANCE = "REFINANCE"


class RefusalReason(str, Enum):
    DEFAULT_NOTICE = "DEFAULT_NOTICE"
    CAPACITY = "CAPACITY"
    DISCRETION = "DISCRETION"


class TerminationCause(str, Enum):
    FOR_CAUSE_QA = "FOR_CAUSE_QA"
    FOR_CAUSE_PIP = "FOR_CAUSE_PIP"
    MUTUAL = "MUTUAL"


class LiquidatedDamagesFormula(str, Enum):
    CONTRACTUAL_MULTIPLE = "CONTRACTUAL_MULTIPLE"
    DISCOUNTED_PV = "DISCOUNTED_PV"


class DeIdentificationItem(str, Enum):
    SIGNAGE = "SIGNAGE"
    INTERIOR_BRANDING = "INTERIOR_BRANDING"
    DIGITAL_LISTINGS = "DIGITAL_LISTINGS"
    LINENS_AND_COLLATERAL = "LINENS_AND_COLLATERAL"
    RESERVATION_CODES = "RESERVATION_CODES"


class OnboardingTrack(str, Enum):
    TRAINING = "TRAINING"
    SYSTEMS = "SYSTEMS"
    CHANNEL = "CHANNEL"


# ─── Entity shapes ───────────────────────────────────────────────────
# Every one of the ten resource families exposes id, created_at,
# updated_at and version (PRD §2.5).


class Brand(TypedDict):
    id: str
    code: str
    name: str
    tier: str
    base_royalty_rate_pct: float
    marketing_fund_rate_pct: float
    protected_radius_miles: float
    min_room_count: int
    standard_term_years: int
    operating_unit_count: int
    open_application_count: int
    created_at: str
    updated_at: str
    version: int


class Owner(TypedDict):
    id: str
    legal_name: str
    contact_email: str
    liquid_assets_amount: float
    net_worth_amount: float
    credit_score: int
    existing_units_count: int
    status: str
    financial_profile_revision: int
    capacity_score_standalone: float
    capacity_band_standalone: str
    capacity_score_portfolio_adjusted: float
    capacity_band_portfolio_adjusted: str
    created_at: str
    updated_at: str
    version: int


class ExistingUnit(TypedDict):
    id: str
    brand_id: str
    unit_name: str
    market_code: str
    x_miles: float
    y_miles: float
    room_count: int
    adr_amount: float
    occupancy_pct: float
    territory_start_date: str
    territory_end_date: str
    status: str
    status_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict):
    id: str
    owner_id: str
    brand_id: str
    property_name: str
    market_code: str
    property_x_miles: float
    property_y_miles: float
    room_count: int
    current_affiliation: str
    building_age_years: int
    requested_term_years: int
    requested_conversion_date: str
    status: str
    financial_review_status: str
    impact_study_status: str
    revision_round: int
    revision_notes: Optional[str]
    revision_response: Optional[str]
    capacity_basis: Optional[str]
    capacity_score_at_review: Optional[float]
    capacity_band_at_review: Optional[str]
    financial_reviewer_user_id: Optional[str]
    reviewer_notes: Optional[str]
    preliminary_impact_score: Optional[float]
    impact_unit_count_preliminary: Optional[int]
    base_impact_score: Optional[float]
    final_impact_score: Optional[float]
    impact_unit_count_final: Optional[int]
    encroachment_verdict: Optional[str]
    claim_window_closes_at: Optional[str]
    sustained_claim_count: int
    decision_outcome: Optional[str]
    decision_notes: Optional[str]
    decision_user_id: Optional[str]
    decided_at: Optional[str]
    encroachment_waiver_granted: bool
    created_at: str
    updated_at: str
    version: int


class EncroachmentClaim(TypedDict):
    id: str
    application_id: str
    existing_unit_id: str
    claimed_revenue_loss_pct: float
    narrative: str
    distance_miles: float
    status: str
    penalty_points_applied: float
    filed_by_user_id: str
    resolution_notes: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RevenuePeriod(TypedDict):
    period_month: str
    gross_room_revenue: float
    royalty_fee: float
    marketing_fee: float
    reservation_fee: float
    period_total_fee: float
    superseded: bool


class LicenseAgreement(TypedDict):
    id: str
    application_id: str
    brand_code: str
    effective_date: str
    expiry_date: str
    term_years: int
    royalty_rate_pct: float
    marketing_fund_rate_pct: float
    liquidated_damages_cap_months: int
    status: str
    compliance_status: str
    training_status: str
    systems_status: str
    channel_status: str
    de_identification_status: str
    de_identification_deadline: Optional[str]
    de_identification_items_completed: List[str]
    de_identification_breach_penalty: float
    post_termination_status: str
    consecutive_qa_failure_count: int
    revenue_periods: List[RevenuePeriod]
    reported_period_count: int
    royalty_fee_to_date: float
    marketing_fund_contributed_total: float
    reservation_fee_to_date: float
    total_fees_assessed: float
    transfer_consent_blocked: bool
    transfer_consent_count: int
    liquidated_damages_paid_amount: float
    termination_cause: Optional[str]
    liquidated_damages_formula: Optional[str]
    liquidated_damages_amount: Optional[float]
    remaining_term_months_at_termination: Optional[int]
    trailing_avg_monthly_fee: Optional[float]
    default_notice_issued_at: Optional[str]
    pip_cure_deadline: Optional[str]
    executed_at: Optional[str]
    opened_at: Optional[str]
    last_inspection_at: Optional[str]
    terminated_at: Optional[str]
    closed_out_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PropertyImprovementPlan(TypedDict):
    id: str
    agreement_id: str
    scope_notes: str
    status: str
    items_total_count: int
    items_pending_count: int
    items_submitted_count: int
    items_verified_count: int
    items_overdue_count: int
    total_estimated_cost: float
    cost_per_room: float
    key_money_pct: int
    franchisor_key_money: float
    owner_net_cost: float
    owner_net_cost_per_room: float
    escalation_required: bool
    extension_granted_days_total: int
    accepted_at: Optional[str]
    overall_deadline: Optional[str]
    acknowledgement: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PipItem(TypedDict):
    id: str
    pip_id: str
    category: str
    priority: str
    description: str
    estimated_cost: float
    status: str
    extension_status: str
    extension_requested_days: int
    extension_granted_days_total: int
    extension_request_count: int
    extension_reason: Optional[str]
    rejection_count: int
    base_due_date: Optional[str]
    due_date: Optional[str]
    completion_evidence: Optional[str]
    completed_at: Optional[str]
    verified_at: Optional[str]
    overdue_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class QaInspection(TypedDict):
    id: str
    agreement_id: str
    cleanliness_score: int
    condition_score: int
    brand_standard_score: int
    guest_experience_score: int
    critical_defect_count: int
    life_safety_defect: bool
    weighted_score: float
    total_score: float
    grade: str
    status: str
    cure_period_days: Optional[int]
    cure_deadline: Optional[str]
    inspection_at: str
    inspector_user_id: str
    cure_evidence: Optional[str]
    cure_submitted_at: Optional[str]
    cure_reviewer_user_id: Optional[str]
    cure_reviewed_at: Optional[str]
    review_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransferRequest(TypedDict):
    id: str
    agreement_id: str
    request_type: str
    proposed_owner_id: Optional[str]
    lender_name: Optional[str]
    status: str
    submitted_by_user_id: str
    proposed_owner_capacity_band: Optional[str]
    transfer_fee: float
    non_compliance_surcharge: float
    total_consent_fee: float
    refusal_reason: Optional[str]
    decision_user_id: Optional[str]
    decision_notes: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
