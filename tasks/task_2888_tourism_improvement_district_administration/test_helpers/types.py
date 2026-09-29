"""Domain types for the Tourism Improvement District Administration API.

Enumerations and entity shapes, named exactly as the PRD names them.  All
twelve persisted resource types carry ``id``, ``created_at``, ``updated_at``
and ``version`` (PRD 2.5).
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------
# Identity and access control (PRD 2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    DISTRICT_ADMINISTRATOR = "DistrictAdministrator"
    BOARD_MEMBER = "BoardMember"
    LODGING_OPERATOR = "LodgingOperator"
    DMO_LIAISON = "DmoLiaison"
    HEARING_OFFICER = "HearingOfficer"
    INDEPENDENT_AUDITOR = "IndependentAuditor"
    PUBLIC_VIEWER = "PublicViewer"


ALL_ROLES: List[str] = [r.value for r in UserRole]


# --------------------------------------------------------------------------
# District (PRD 3.1)
# --------------------------------------------------------------------------
class DistrictStatus(str, Enum):
    PROPOSED = "PROPOSED"
    PETITION_CIRCULATING = "PETITION_CIRCULATING"
    FORMATION_FAILED = "FORMATION_FAILED"
    FORMED = "FORMED"
    ACTIVE = "ACTIVE"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    EXPIRED = "EXPIRED"
    DISESTABLISHED = "DISESTABLISHED"


class AssessmentMethod(str, Enum):
    PCT_OF_ROOM_REVENUE = "PCT_OF_ROOM_REVENUE"
    PER_OCCUPIED_ROOM_NIGHT = "PER_OCCUPIED_ROOM_NIGHT"
    TIERED_BY_CLASSIFICATION = "TIERED_BY_CLASSIFICATION"


class BoundaryZone(str, Enum):
    ZONE_CORE = "ZONE_CORE"
    ZONE_PERIMETER = "ZONE_PERIMETER"
    OUTSIDE = "OUTSIDE"


class TransparencyStanding(str, Enum):
    COMPLIANT = "COMPLIANT"
    DEFICIENT = "DEFICIENT"


class DmoAgreementStatus(str, Enum):
    NONE = "NONE"
    PROPOSED = "PROPOSED"
    EXECUTED = "EXECUTED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


# --------------------------------------------------------------------------
# Lodging business (PRD 3.1)
# --------------------------------------------------------------------------
class LodgingBusinessStatus(str, Enum):
    ASSESSABLE = "ASSESSABLE"
    EXEMPT = "EXEMPT"
    OUTSIDE_BOUNDARY = "OUTSIDE_BOUNDARY"
    CLOSED_OUT = "CLOSED_OUT"


class Classification(str, Enum):
    FULL_SERVICE = "FULL_SERVICE"
    LIMITED_SERVICE = "LIMITED_SERVICE"
    BOUTIQUE = "BOUTIQUE"
    SHORT_TERM_RENTAL = "SHORT_TERM_RENTAL"


class ExemptStatus(str, Enum):
    NONE = "NONE"
    GOVERNMENT_OWNED = "GOVERNMENT_OWNED"
    UNDER_MINIMUM_ROOMS = "UNDER_MINIMUM_ROOMS"
    NONPROFIT_RETREAT = "NONPROFIT_RETREAT"


class RemittanceFrequency(str, Enum):
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"


class ComplianceStanding(str, Enum):
    GOOD = "GOOD"
    WATCH = "WATCH"
    SUSPENDED = "SUSPENDED"


# --------------------------------------------------------------------------
# Petition drives and signatures (PRD 3.2)
# --------------------------------------------------------------------------
class DriveType(str, Enum):
    FORMATION = "FORMATION"
    RENEWAL = "RENEWAL"


class PetitionDriveStatus(str, Enum):
    OPEN = "OPEN"
    QUALIFIED = "QUALIFIED"
    SHORT_OF_THRESHOLD = "SHORT_OF_THRESHOLD"
    CERTIFIED = "CERTIFIED"
    WITHDRAWN = "WITHDRAWN"


class ShortReason(str, Enum):
    NONE = "NONE"
    WEIGHTED_BELOW_THRESHOLD = "WEIGHTED_BELOW_THRESHOLD"
    HEADCOUNT_BELOW_MINIMUM = "HEADCOUNT_BELOW_MINIMUM"


class SignatureStatus(str, Enum):
    VALID = "VALID"
    WITHDRAWN = "WITHDRAWN"
    DISQUALIFIED = "DISQUALIFIED"


class DisqualificationReason(str, Enum):
    NONE = "NONE"
    COMPLIANCE_SUSPENDED = "COMPLIANCE_SUSPENDED"
    OUTSIDE_BOUNDARY = "OUTSIDE_BOUNDARY"
    BUSINESS_EXEMPT = "BUSINESS_EXEMPT"


# --------------------------------------------------------------------------
# Assessment periods and statements (PRD 3.3)
# --------------------------------------------------------------------------
class AssessmentPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    DELINQUENCY_SWEPT = "DELINQUENCY_SWEPT"


class FilingStatus(str, Enum):
    NOT_FILED = "NOT_FILED"
    FILED = "FILED"
    AMENDED = "AMENDED"
    AUDITED = "AUDITED"
    CERTIFIED = "CERTIFIED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    DELINQUENT = "DELINQUENT"
    REFUND_DUE = "REFUND_DUE"


class DelinquencyStage(str, Enum):
    NONE = "NONE"
    NOTICE = "NOTICE"
    LIEN_REFERRED = "LIEN_REFERRED"


class AuditAction(str, Enum):
    AUDIT = "AUDIT"
    CERTIFY = "CERTIFY"


# --------------------------------------------------------------------------
# Remittances (PRD 3.4)
# --------------------------------------------------------------------------
class RemittanceMethod(str, Enum):
    ACH = "ACH"
    CHECK = "CHECK"
    WIRE = "WIRE"
    CARD = "CARD"


class RemittanceStatus(str, Enum):
    APPLIED = "APPLIED"
    REVERSED = "REVERSED"


# --------------------------------------------------------------------------
# Disputes (PRD 3.6)
# --------------------------------------------------------------------------
class DisputeType(str, Enum):
    CALCULATION_ERROR = "CALCULATION_ERROR"
    EXEMPT_PROPERTY = "EXEMPT_PROPERTY"
    BOUNDARY_MISCLASSIFICATION = "BOUNDARY_MISCLASSIFICATION"


class DisputeStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_ADJUSTED = "RESOLVED_ADJUSTED"
    WITHDRAWN = "WITHDRAWN"


class DisputeAction(str, Enum):
    OPEN_REVIEW = "OPEN_REVIEW"
    REQUEST_INFO = "REQUEST_INFO"
    SUBMIT_RESPONSE = "SUBMIT_RESPONSE"
    APPEAL = "APPEAL"
    WITHDRAW = "WITHDRAW"


class DisputeOutcome(str, Enum):
    UPHELD = "UPHELD"
    ADJUSTED = "ADJUSTED"


# --------------------------------------------------------------------------
# Annual work plans (PRD 3.7)
# --------------------------------------------------------------------------
class WorkPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    BOARD_REVIEW = "BOARD_REVIEW"
    APPROVED = "APPROVED"
    AMENDMENT_PENDING = "AMENDMENT_PENDING"
    CLOSED = "CLOSED"


class ExpenditureCategory(str, Enum):
    SALES_AND_MARKETING = "SALES_AND_MARKETING"
    DESTINATION_EVENTS = "DESTINATION_EVENTS"
    ADMINISTRATION = "ADMINISTRATION"
    CONTINGENCY_RESERVE = "CONTINGENCY_RESERVE"
    CAPITAL_IMPROVEMENT = "CAPITAL_IMPROVEMENT"


class BoardAction(str, Enum):
    SPONSOR = "SPONSOR"
    APPROVE = "APPROVE"
    RETURN = "RETURN"
    CLOSE = "CLOSE"


# --------------------------------------------------------------------------
# Marketing programs, claims and performance (PRD 3.8)
# --------------------------------------------------------------------------
class MarketingProgramStatus(str, Enum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    SUSPENDED_PENDING_AMENDMENT = "SUSPENDED_PENDING_AMENDMENT"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class MarketingChannel(str, Enum):
    PAID_SEARCH = "PAID_SEARCH"
    TRADE_SHOW = "TRADE_SHOW"
    GROUP_SALES = "GROUP_SALES"
    OTA_CAMPAIGN = "OTA_CAMPAIGN"
    INFLUENCER = "INFLUENCER"


class EfficiencyTier(str, Enum):
    TIER_EFFICIENT = "TIER_EFFICIENT"
    TIER_STANDARD = "TIER_STANDARD"
    TIER_MARGINAL = "TIER_MARGINAL"
    TIER_UNPRODUCTIVE = "TIER_UNPRODUCTIVE"


class PerformanceFlag(str, Enum):
    NOT_MEASURED = "NOT_MEASURED"
    MEETS_BENCHMARK = "MEETS_BENCHMARK"
    BELOW_BENCHMARK = "BELOW_BENCHMARK"
    UNDERPERFORMING = "UNDERPERFORMING"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class AttributionMethod(str, Enum):
    DIRECT_PICKUP = "DIRECT_PICKUP"
    LOOKBACK_WINDOW = "LOOKBACK_WINDOW"


class ClaimRejectionReason(str, Enum):
    NONE = "NONE"
    UNVERIFIABLE = "UNVERIFIABLE"
    DUPLICATE_STAY = "DUPLICATE_STAY"
    OUTSIDE_ATTRIBUTION_WINDOW = "OUTSIDE_ATTRIBUTION_WINDOW"


class VerificationDecision(str, Enum):
    ALLOW = "ALLOW"
    REJECT = "REJECT"


# --------------------------------------------------------------------------
# Transparency records (PRD 3.9)
# --------------------------------------------------------------------------
class TransparencyRecordType(str, Enum):
    PUBLIC_MEETING = "PUBLIC_MEETING"
    ANNUAL_REPORT = "ANNUAL_REPORT"
    FINANCIAL_AUDIT = "FINANCIAL_AUDIT"


class TransparencyRecordStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    NOTICED = "NOTICED"
    COMPLETED = "COMPLETED"
    PUBLISHED = "PUBLISHED"
    OVERDUE = "OVERDUE"


# --------------------------------------------------------------------------
# Entity shapes.  Every persisted type carries the four common properties of
# PRD 2.5; the shapes below are read-side views used for documentation and
# static reference by the suite.
# --------------------------------------------------------------------------
class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class District(CommonFields, total=False):
    name: str
    status: str
    assessment_method: str
    included_zones: List[str]
    formation_threshold_pct: float
    renewal_threshold_pct: float
    renewal_headcount_threshold_pct: float
    term_years: int
    current_fiscal_year: int
    formed_on: Optional[str]
    expiration_date: Optional[str]
    transparency_standing: str
    dmo_name: Optional[str]
    dmo_agreement_status: str
    dmo_contract_cents: int
    public_lodging_tax_offset_cents: int
    lodging_tax_match_pool_cents: int
    lodging_tax_match_committed_cents: int
    collected_to_date_cents: int
    delinquent_charges_cents: int
    assessable_basis_cents: int
    assessable_business_count: int


class LodgingBusiness(CommonFields, total=False):
    district_id: str
    legal_name: str
    boundary_zone: str
    classification: str
    room_count: int
    prior_year_gross_room_revenue_cents: int
    operator_contact_email: str
    exempt_status: str
    remittance_frequency: str
    status: str
    delinquency_strike_count: int
    compliance_standing: str


class PetitionDrive(CommonFields, total=False):
    district_id: str
    drive_type: str
    status: str
    opened_on: str
    closes_at: str
    required_weighted_pct: float
    required_headcount_pct: float
    assessable_basis_snapshot_cents: int
    assessable_count_snapshot: int
    signed_basis_cents: int
    valid_signature_count: int
    weighted_support_pct: float
    headcount_support_pct: float
    short_reason: str
    tallied_at: Optional[str]
    certified_on: Optional[str]


class PetitionSignature(CommonFields, total=False):
    petition_drive_id: str
    lodging_business_id: str
    signed_at: str
    weight_basis_revenue_cents: int
    status: str
    disqualification_reason: str
    reason: Optional[str]


class AssessmentPeriod(CommonFields, total=False):
    district_id: str
    period_label: str
    period_start: str
    period_end: str
    due_date: str
    grace_days: int
    status: str
    statement_count: int
    billed_total_cents: int
    collected_total_cents: int


class AssessmentStatement(CommonFields, total=False):
    assessment_period_id: str
    lodging_business_id: str
    zone_at_period_start: str
    classification_at_period_start: str
    assessment_method_at_period_start: str
    filing_status: str
    payment_status: str
    reported_room_nights: Optional[int]
    reported_gross_room_revenue_cents: Optional[int]
    audited_room_nights: Optional[int]
    audited_gross_room_revenue_cents: Optional[int]
    provisional_assessment_cents: int
    final_assessment_cents: Optional[int]
    effective_assessment_cents: int
    granted_adjustment_cents: int
    delinquency_stage: str
    penalty_cents: int
    interest_cents: int
    interest_paid_cents: int
    penalty_paid_cents: int
    principal_paid_cents: int
    credit_balance_cents: int
    total_due_cents: int
    amendment_count: int
    filed_at: Optional[str]
    audited_by_user_id: Optional[str]
    audit_note: Optional[str]


class Remittance(CommonFields, total=False):
    assessment_statement_id: str
    amount_cents: int
    received_on: str
    method: str
    status: str
    applied_to_interest_cents: int
    applied_to_penalty_cents: int
    applied_to_principal_cents: int
    applied_to_credit_cents: int
    reversed_on: Optional[str]
    reversal_reason: Optional[str]


class ExpenditureLine(TypedDict, total=False):
    category: str
    amount_cents: int
    narrative: str


class AnnualWorkPlan(CommonFields, total=False):
    district_id: str
    fiscal_year: int
    status: str
    expenditure_lines: List[ExpenditureLine]
    total_budget_cents: int
    administration_cents: int
    contingency_reserve_cents: int
    sales_and_marketing_cents: int
    destination_events_cents: int
    capital_improvement_cents: int
    assessment_revenue_forecast_cents: int
    funding_ratio: float
    committed_program_cents: int
    revision_count: int
    sponsor_user_id: Optional[str]
    approver_user_id: Optional[str]
    approved_at: Optional[str]


class MarketingProgram(CommonFields, total=False):
    annual_work_plan_id: str
    name: str
    channel: str
    status: str
    committed_cents: int
    lodging_tax_matched_cents: int
    booking_window_start: str
    booking_window_end: str
    spend_frozen: bool
    verified_room_nights: int
    gross_cost_per_room_night_cents: Optional[int]
    efficiency_tier: Optional[str]
    dmo_cost_share_cents: int
    net_district_cost_cents: int
    net_cost_per_room_night_cents: Optional[int]
    performance_index: float
    performance_flag: str
    launched_at: Optional[str]
    closed_at: Optional[str]


class RoomNightClaim(CommonFields, total=False):
    marketing_program_id: str
    lodging_business_id: str
    stay_start: str
    stay_end: str
    room_nights: int
    attribution_method: str
    status: str
    verified_room_nights: Optional[int]
    rejection_reason: str
    verified_by_user_id: Optional[str]


class TransparencyRecord(CommonFields, total=False):
    district_id: str
    record_type: str
    fiscal_year: int
    status: str
    scheduled_for: str
    required_by: str
    noticed_on: Optional[str]
    completed_on: Optional[str]
    published_on: Optional[str]
    document_reference: Optional[str]
    engaged_by_user_id: str


class AssessmentDispute(CommonFields, total=False):
    assessment_statement_id: str
    lodging_business_id: str
    dispute_type: str
    status: str
    claimed_adjustment_cents: int
    granted_adjustment_cents: int
    appeal_count: int
    filed_on: str
    dispute_note: Optional[str]
    resolution_note: Optional[str]
    resolved_by_user_id: Optional[str]
    exempt_status_granted: Optional[str]


# A generic JSON object as returned inside the envelope's ``data`` field.
JsonObject = Dict[str, Any]
