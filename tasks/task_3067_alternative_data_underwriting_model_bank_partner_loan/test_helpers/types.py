"""Domain types: entity TypedDicts, status enums, role enum.

Entities with the full common field set carry id, created_at, updated_at, and
version. Immutable records (ServicingEvent, AllocationDecision) carry only id
and created_at.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    RISK_OFFICER = "RiskOfficer"
    PARTNER_ADMIN = "PartnerAdmin"
    VERIFICATION_OFFICER = "VerificationOfficer"
    SERVICING_AGENT = "ServicingAgent"
    COLLECTIONS_AGENT = "CollectionsAgent"
    AUDITOR = "Auditor"


class ModelVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class PartnerStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDED = "OFFBOARDED"


class PartnerType(str, Enum):
    BANK = "BANK"
    CREDIT_UNION = "CREDIT_UNION"
    LOAN_BUYER = "LOAN_BUYER"
    SECURITIZATION_TRUST = "SECURITIZATION_TRUST"


class CreditBoxStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class EducationLevel(str, Enum):
    HIGH_SCHOOL = "HIGH_SCHOOL"
    ASSOCIATE = "ASSOCIATE"
    BACHELOR = "BACHELOR"
    MASTER = "MASTER"
    DOCTORATE = "DOCTORATE"


class EmploymentStatus(str, Enum):
    EMPLOYED = "EMPLOYED"
    SELF_EMPLOYED = "SELF_EMPLOYED"
    UNEMPLOYED = "UNEMPLOYED"
    RETIRED = "RETIRED"


class ApplicationChannel(str, Enum):
    DIRECT = "DIRECT"
    PARTNER_REFERRAL = "PARTNER_REFERRAL"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFICATION_PENDING = "VERIFICATION_PENDING"
    DOCS_REQUIRED = "DOCS_REQUIRED"
    UNDERWRITTEN = "UNDERWRITTEN"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class VerificationKind(str, Enum):
    INCOME = "INCOME"
    IDENTITY = "IDENTITY"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    INSTANT_PASSED = "INSTANT_PASSED"
    INSTANT_FAILED = "INSTANT_FAILED"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    MANUAL_PASSED = "MANUAL_PASSED"
    MANUAL_FAILED = "MANUAL_FAILED"


class ReviewType(str, Enum):
    VARIABLE_EXCLUSION = "VARIABLE_EXCLUSION"
    DISPARATE_IMPACT = "DISPARATE_IMPACT"


class ReviewOutcome(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class LoanStatus(str, Enum):
    FUNDED = "FUNDED"
    CURRENT = "CURRENT"
    DELINQUENT = "DELINQUENT"
    DEFAULTED = "DEFAULTED"
    CHARGED_OFF = "CHARGED_OFF"
    PAID_OFF = "PAID_OFF"


class AllocationChannel(str, Enum):
    PARTNER_RETAINED = "PARTNER_RETAINED"
    REFERRAL_RETAINED = "REFERRAL_RETAINED"
    WHOLE_LOAN_SALE = "WHOLE_LOAN_SALE"
    SECURITIZATION = "SECURITIZATION"
    UNALLOCATED = "UNALLOCATED"


class ServicingEventType(str, Enum):
    PAYMENT_APPLIED = "PAYMENT_APPLIED"
    LATE_FEE_ASSESSED = "LATE_FEE_ASSESSED"
    DELINQUENCY_ADVANCED = "DELINQUENCY_ADVANCED"
    DEFAULT_DECLARED = "DEFAULT_DECLARED"
    CHARGE_OFF_REPORTED = "CHARGE_OFF_REPORTED"
    PAYOFF_RECORDED = "PAYOFF_RECORDED"


class PoolStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ReasonCode(str, Enum):
    PARTNER_INACTIVE = "PARTNER_INACTIVE"
    NO_ACTIVE_CREDIT_BOX = "NO_ACTIVE_CREDIT_BOX"
    STATE_NOT_ALLOWED = "STATE_NOT_ALLOWED"
    SCORE_BELOW_BOX = "SCORE_BELOW_BOX"
    SCORE_ABOVE_BOX = "SCORE_ABOVE_BOX"
    AMOUNT_BELOW_BOX = "AMOUNT_BELOW_BOX"
    AMOUNT_ABOVE_BOX = "AMOUNT_ABOVE_BOX"
    VOLUME_CAP_REACHED = "VOLUME_CAP_REACHED"
    POOL_SINGLE_LOAN_EXCEEDED = "POOL_SINGLE_LOAN_EXCEEDED"
    POOL_CAPACITY_EXCEEDED = "POOL_CAPACITY_EXCEEDED"
    AFFORDABILITY_ZERO = "AFFORDABILITY_ZERO"


# --- Entity TypedDicts -------------------------------------------------------

class ModelVersion(TypedDict, total=False):
    id: str
    model_code: str
    variables: List[Dict[str, Any]]
    calibration_note: str
    score_floor: int
    score_ceiling: int
    status: str
    fairness_report: Optional[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class Partner(TypedDict, total=False):
    id: str
    legal_name: str
    partner_type: str
    home_state: str
    status: str
    active_credit_box_id: Optional[str]
    originated_this_month_count: int
    funded_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class CreditBox(TypedDict, total=False):
    id: str
    partner_id: str
    min_score: int
    max_score: int
    allowed_states: List[str]
    min_loan_cents: int
    max_loan_cents: int
    monthly_volume_cap_count: int
    annual_percentage_rate: float
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Applicant(TypedDict, total=False):
    id: str
    full_name: str
    state_code: str
    annual_income_cents: int
    monthly_debt_payments_cents: int
    education_level: str
    employment_status: str
    months_employed: int
    bank_account_avg_balance_cents: int
    bank_account_nsf_count_90d: int
    monthly_net_cashflow_cents: int
    bureau_score: int
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    applicant_id: str
    channel: str
    referral_partner_id: Optional[str]
    requested_amount_cents: int
    model_version_id: str
    risk_score: int
    approved_amount_cents: Optional[int]
    debt_to_income_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Verification(TypedDict, total=False):
    id: str
    application_id: str
    kind: str
    status: str
    reviewer_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FairnessReview(TypedDict, total=False):
    id: str
    model_version_id: str
    review_type: str
    outcome: str
    details: str
    created_at: str
    updated_at: str
    version: int


class Attestation(TypedDict, total=False):
    id: str
    model_version_id: str
    partner_id: str
    period_label: str
    expected_default_rate_bps: int
    actual_default_rate_bps: int
    variance_bps: int
    attested_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    application_id: str
    holder_partner_id: str
    allocation_channel: str
    principal_cents: int
    apr: float
    term_months: int
    monthly_payment_cents: int
    scheduled_interest_cents: int
    late_fee_accrued_cents: int
    outstanding_principal_cents: int
    days_delinquent: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable record: only id + created_at are guaranteed by the common set.
class ServicingEvent(TypedDict, total=False):
    id: str
    loan_id: str
    event_type: str
    amount_cents: int
    occurred_at: str
    resulting_loan_status: str
    note: Optional[str]
    created_at: str


class SecuritizationPool(TypedDict, total=False):
    id: str
    trust_partner_id: str
    pool_label: str
    target_principal_cents: int
    allocated_principal_cents: int
    max_single_loan_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable record: only id + created_at are guaranteed by the common set.
class AllocationDecision(TypedDict, total=False):
    id: str
    application_id: str
    candidate_partner_ids: List[str]
    chosen_partner_id: Optional[str]
    channel: str
    reason_codes: List[str]
    decided_at: str
    created_at: str
