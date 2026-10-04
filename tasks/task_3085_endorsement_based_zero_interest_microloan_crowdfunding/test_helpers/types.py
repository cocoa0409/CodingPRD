"""Domain types: entity TypedDicts, status enums, role enum.

Only PRD-declared fields appear here. UnderwritingInvite and Payment are
append-only records that carry only ``id`` and ``created_at`` plus their
own payload fields; they intentionally omit ``updated_at`` and ``version``.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    BORROWER = "Borrower"
    LENDER = "Lender"
    TRUSTEE = "Trustee"
    PLATFORM_ADMIN = "PlatformAdmin"


class BorrowerStatus(str, Enum):
    REGISTERED = "REGISTERED"
    RESTRICTED = "RESTRICTED"


class UnderwritingVariant(str, Enum):
    NONE = "NONE"
    STANDARD = "STANDARD"
    TRUSTEE_AUGMENTED = "TRUSTEE_AUGMENTED"


class InviteStatus(str, Enum):
    SENT = "SENT"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"


class TrusteeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class SuspensionReason(str, Enum):
    NONE = "NONE"
    MANUAL = "MANUAL"
    DEFAULT_RATE = "DEFAULT_RATE"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED_PENDING_FUNDRAISE = "APPROVED_PENDING_FUNDRAISE"
    PRIVATE_FUNDRAISING = "PRIVATE_FUNDRAISING"
    PUBLIC_FUNDRAISING = "PUBLIC_FUNDRAISING"
    FUNDED = "FUNDED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED_PRIVATE = "EXPIRED_PRIVATE"
    EXPIRED_PUBLIC = "EXPIRED_PUBLIC"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class EndorsementMode(str, Enum):
    SELF_ENDORSED = "SELF_ENDORSED"
    TRUSTEE_VOUCHED = "TRUSTEE_VOUCHED"


class EndorsementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"
    CONVERTED = "CONVERTED"


class ContributionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REFUNDED = "REFUNDED"
    CONVERTED = "CONVERTED"


class LoanStatus(str, Enum):
    REPAYING = "REPAYING"
    DELINQUENT = "DELINQUENT"
    PAID_OFF = "PAID_OFF"
    DEFAULTED = "DEFAULTED"


class ScheduleStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class InstallmentStatus(str, Enum):
    PENDING = "PENDING"
    DUE = "DUE"
    PARTIAL = "PARTIAL"
    PAID = "PAID"
    LATE = "LATE"


class Borrower(TypedDict, total=False):
    id: str
    legal_name: str
    business_name: str
    email: str
    business_tenure_months: int
    prior_repaid_loans_count: int
    status: str
    social_underwriting_score: float
    underwriting_variant: str
    completed_loan_count: int
    defaulted_loan_count: int
    restricted_since: Optional[str]
    created_at: str
    updated_at: str
    version: int


class UnderwritingInvite(TypedDict, total=False):
    # Append-only record: id + created_at only, no updated_at / version.
    id: str
    created_at: str
    borrower_id: str
    invitee_email: str
    invite_token: str
    status: str
    responded_at: Optional[str]


class Lender(TypedDict, total=False):
    id: str
    display_name: str
    email: str
    lending_balance_cents: int
    total_deposited_cents: int
    lifetime_lent_cents: int
    lifetime_repaid_cents: int
    created_at: str
    updated_at: str
    version: int


class Trustee(TypedDict, total=False):
    id: str
    org_name: str
    endorsement_limit_cents: int
    status: str
    suspension_reason: str
    active_endorsement_exposure_cents: int
    endorsed_terminal_count: int
    endorsed_defaulted_count: int
    default_rate_bps: int
    created_at: str
    updated_at: str
    version: int


class LoanApplication(TypedDict, total=False):
    id: str
    borrower_id: str
    trustee_id: Optional[str]
    requested_amount_cents: int
    term_months: int
    business_purpose: str
    endorsement_mode: str
    required_endorser_count: int
    distinct_endorser_count: int
    private_total_cents: int
    public_total_cents: int
    funded_total_cents: int
    status: str
    review_notes: Optional[str]
    private_started_at: Optional[str]
    private_deadline: Optional[str]
    public_started_at: Optional[str]
    public_deadline: Optional[str]
    funded_at: Optional[str]
    terminal_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Endorsement(TypedDict, total=False):
    id: str
    loan_application_id: str
    lender_id: Optional[str]
    amount_cents: int
    is_trustee_endorsement: bool
    trustee_id: Optional[str]
    status: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Contribution(TypedDict, total=False):
    id: str
    loan_application_id: str
    lender_id: str
    amount_cents: int
    status: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    loan_application_id: str
    borrower_id: str
    principal_cents: int
    term_months: int
    disbursed_at: str
    status: str
    schedule_status: str
    provisional_base_cents: int
    final_base_cents: Optional[int]
    final_first_cents: Optional[int]
    outstanding_cents: int
    delinquent_since: Optional[str]
    defaulted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Installment(TypedDict, total=False):
    id: str
    loan_id: str
    installment_number: int
    due_date: str
    amount_due_cents: int
    amount_paid_cents: int
    remaining_cents: int
    status: str
    paid_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    # Append-only record: id + created_at only, no updated_at / version.
    id: str
    created_at: str
    loan_id: str
    borrower_id: str
    amount_cents: int
    paid_at: str


class ImpactReport(TypedDict, total=False):
    id: str
    loan_id: str
    borrower_id: str
    months_after_disbursement: int
    revenue_change_pct: int
    jobs_created: int
    narrative: str
    is_mid_term: bool
    created_at: str
    updated_at: str
    version: int
