"""Domain types: entity TypedDicts, status enums and the role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    BORROWER = "Borrower"
    COSIGNER = "Cosigner"
    SCHOOL = "School"
    UNDERWRITER = "Underwriter"
    SERVICER = "Servicer"
    PLATFORM_ADMIN = "PlatformAdmin"


class BorrowerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    LOCKED = "LOCKED"


class EnrollmentStatus(str, Enum):
    IN_SCHOOL = "IN_SCHOOL"
    LESS_THAN_HALF_TIME = "LESS_THAN_HALF_TIME"
    GRADUATED = "GRADUATED"
    WITHDRAWN = "WITHDRAWN"


class ProgramLevel(str, Enum):
    UNDERGRADUATE = "UNDERGRADUATE"
    GRADUATE = "GRADUATE"


class CosignerUnderwritingStatus(str, Enum):
    INVITED = "INVITED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    RELEASED = "RELEASED"


class Relationship(str, Enum):
    PARENT = "PARENT"
    GRANDPARENT = "GRANDPARENT"
    SIBLING = "SIBLING"
    SPOUSE = "SPOUSE"
    OTHER = "OTHER"


class InterestAccrualOption(str, Enum):
    DEFERRED = "DEFERRED"
    INTEREST_ONLY = "INTEREST_ONLY"
    IMMEDIATE = "IMMEDIATE"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    SCHOOL_CERT_PENDING = "SCHOOL_CERT_PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"
    DISBURSED = "DISBURSED"
    CLOSED = "CLOSED"


class CertificationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CERTIFIED = "CERTIFIED"
    PARTIAL_CERTIFIED = "PARTIAL_CERTIFIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class LoanStatus(str, Enum):
    APPROVED = "APPROVED"
    IN_SCHOOL = "IN_SCHOOL"
    GRACE = "GRACE"
    REPAYMENT = "REPAYMENT"
    FORBEARANCE_DEFERMENT = "FORBEARANCE_DEFERMENT"
    DELINQUENT = "DELINQUENT"
    DEFAULT = "DEFAULT"
    PAID_IN_FULL = "PAID_IN_FULL"


class DisbursementStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class RefundStatus(str, Enum):
    NOT_APPLICABLE = "NOT_APPLICABLE"
    REFUND_DUE = "REFUND_DUE"
    REFUNDED = "REFUNDED"


class PlanStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    DECLINED = "DECLINED"


class PaymentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PAID_ON_TIME = "PAID_ON_TIME"
    PAID_LATE = "PAID_LATE"
    MISSED = "MISSED"
    REVERSED = "REVERSED"


class ReliefStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class ReleaseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class DelinquencyStage(str, Enum):
    CURRENT = "CURRENT"
    LATE = "LATE"
    DELINQUENT = "DELINQUENT"
    DEFAULT_ELIGIBLE = "DEFAULT_ELIGIBLE"


# --- entities with the common system fields (id/created_at/updated_at/version)


class Borrower(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    state_code: str
    program_level: str
    credit_score: int
    dti_ratio: float
    enrollment_status: str
    on_time_payment_run_count: int
    lifetime_on_time_payment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Cosigner(TypedDict, total=False):
    id: str
    borrower_id: str
    full_name: str
    email: str
    state_code: str
    relationship: str
    credit_score: int
    credit_history_months: int
    dti_ratio: float
    underwriting_status: str
    created_at: str
    updated_at: str
    version: int


class School(TypedDict, total=False):
    id: str
    name: str
    school_code: str
    state_code: str
    certification_capacity_per_period_cents: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class LoanPolicy(TypedDict, total=False):
    id: str
    product_code: str
    program_level: str
    cosigner_release_min_on_time_payments: int
    cosigner_release_min_credit_score: int
    cosigner_release_max_dti_ratio: float
    autodebit_rate_reduction_pct: float
    autodebit_min_payments_before_reduction: int
    extended_term_months: int
    capitalized_interest_cap_pct: float
    in_school_max_deferment_months: int
    repayment_max_deferment_months: int
    delinquency_notice_threshold_days: int
    allows_standalone_borrower: bool
    created_at: str
    updated_at: str
    version: int


class LoanApplication(TypedDict, total=False):
    id: str
    borrower_id: str
    cosigner_id: Optional[str]
    school_id: str
    policy_id: str
    requested_amount_cents: int
    cost_of_attendance_cents: int
    other_aid_cents: int
    interest_accrual_option: str
    repayment_term_months: int
    certified_limit_cents: int
    combined_credit_score: int
    tier: str
    margin_rate_pct: Optional[float]
    decision_path: Optional[str]
    approved_amount_cents: Optional[int]
    denial_reason: Optional[str]
    application_status: str
    created_at: str
    updated_at: str
    version: int


class SchoolCertification(TypedDict, total=False):
    id: str
    application_id: str
    school_id: str
    academic_period_label: str
    certified_amount_cents: int
    certified_enrollment_status: str
    certified_date: Optional[str]
    certification_status: str
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    borrower_id: str
    application_id: str
    cosigner_id: Optional[str]
    policy_id: str
    principal_cents: int
    disbursed_amount_cents: int
    certified_amount_cents: int
    repayment_entered_date: Optional[str]
    lifetime_accrued_interest_cents: int
    lifetime_capitalized_interest_cents: int
    current_balance_cents: int
    interest_accrual_option: str
    repayment_option: str
    active_plan_type: Optional[str]
    effective_rate_pct: float
    autodebit_enrolled: bool
    autodebit_enrolled_date: Optional[str]
    cumulative_deferment_months: int
    earned_capitalization_count: int
    lifetime_principal_reduction_cents: int
    unpaid_interest_cents: int
    max_allowed_capitalization_cents: int
    max_autodebit_waiver_benefit_cents: int
    disburse_blocked: bool
    certification_limit_cents: int
    days_past_due: int
    delinquency_stage: str
    notice_obligation_status: str
    loan_status: str
    created_at: str
    updated_at: str
    version: int


class Disbursement(TypedDict, total=False):
    id: str
    loan_id: str
    academic_period_label: str
    period_start_date: str
    period_end_date: str
    scheduled_date: str
    amount_cents: int
    released_date: Optional[str]
    remainder_credited_cents: int
    refund_status: str
    disbursement_status: str
    created_at: str
    updated_at: str
    version: int


# InterestAccrualEntry is an append-only ledger row: it carries ONLY id and
# created_at, with neither updated_at nor version.
class InterestAccrualEntry(TypedDict, total=False):
    id: str
    loan_id: str
    entry_date: str
    accrued_amount_cents: int
    entry_status: str
    source_event: str
    created_at: str


class RepaymentPlan(TypedDict, total=False):
    id: str
    loan_id: str
    plan_type: str
    term_months: int
    principal_snapshot_cents: int
    rate_snapshot_pct: float
    monthly_payment_cents: int
    plan_status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    loan_id: str
    due_period_index: int
    scheduled_due_date: str
    paid_date: str
    amount_cents: int
    payment_status: str
    arrear_days: int
    is_qualifying: bool
    created_at: str
    updated_at: str
    version: int


class ForbearanceDeferment(TypedDict, total=False):
    id: str
    loan_id: str
    relief_type: str
    months_requested: int
    interest_treatment: str
    start_date: str
    months_granted: int
    relief_status: str
    created_at: str
    updated_at: str
    version: int


class CosignerReleaseApplication(TypedDict, total=False):
    id: str
    loan_id: str
    cosigner_id: str
    payments_at_application: int
    independent_credit_score: int
    independent_dti_ratio: float
    required_min_payments: int
    run_at_submission: int
    release_status: str
    deficiency_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int