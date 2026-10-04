"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    CLAIMANT = "Claimant"
    EMPLOYER = "Employer"
    CLAIMS_SPECIALIST = "ClaimsSpecialist"
    SENIOR_ADJUDICATOR = "SeniorAdjudicator"
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"


class WorkerStatus(str, Enum):
    LIVING = "LIVING"
    DECEASED = "DECEASED"


class CorrectionRequestStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    EVIDENCE_REQUESTED = "EVIDENCE_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class EvidenceType(str, Enum):
    WAGE_STATEMENT = "WAGE_STATEMENT"
    TAX_RETURN = "TAX_RETURN"
    EMPLOYER_LETTER = "EMPLOYER_LETTER"
    OTHER = "OTHER"


class RelationshipType(str, Enum):
    CURRENT_SPOUSE = "CURRENT_SPOUSE"
    DIVORCED_SPOUSE = "DIVORCED_SPOUSE"
    WIDOW = "WIDOW"


class RelationshipStatus(str, Enum):
    ASSERTED = "ASSERTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class ClaimType(str, Enum):
    RETIREMENT = "RETIREMENT"
    SPOUSAL = "SPOUSAL"
    DIVORCED_SPOUSAL = "DIVORCED_SPOUSAL"
    SURVIVOR = "SURVIVOR"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    ENTITLED = "ENTITLED"
    DENIED = "DENIED"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"
    TERMINATED = "TERMINATED"


class PaymentStatus(str, Enum):
    PAID = "PAID"
    WITHHELD_FULL = "WITHHELD_FULL"
    REPAYED = "REPAYED"


class PaidTo(str, Enum):
    BENEFICIARY = "BENEFICIARY"
    REPRESENTATIVE_PAYEE = "REPRESENTATIVE_PAYEE"


class OverpaymentStatus(str, Enum):
    NOTIFIED = "NOTIFIED"
    WAIVER_REVIEW = "WAIVER_REVIEW"
    WAIVED = "WAIVED"
    RECOVERY_ACTIVE = "RECOVERY_ACTIVE"
    RECOVERED = "RECOVERED"


class OverpaymentReason(str, Enum):
    RECOMPUTATION = "RECOMPUTATION"
    FRAUD = "FRAUD"
    REPORTING_ERROR = "REPORTING_ERROR"
    SYSTEM_ERROR = "SYSTEM_ERROR"


class RecoveryMode(str, Enum):
    FULL = "FULL"
    PARTIAL = "PARTIAL"
    PROPORTIONAL = "PROPORTIONAL"


class PayeeCaseStatus(str, Enum):
    INVESTIGATING = "INVESTIGATING"
    ACTIVE = "ACTIVE"
    DENIED = "DENIED"
    ENDED = "ENDED"


class RecomputationTrigger(str, Enum):
    CORRECTION_APPROVED = "CORRECTION_APPROVED"
    PENSION_UPDATED = "PENSION_UPDATED"
    SUSPENSION_RESUME = "SUSPENSION_RESUME"


class RecomputationResolution(str, Enum):
    UNDERPAYMENT_CREDIT = "UNDERPAYMENT_CREDIT"
    OVERPAYMENT_CREATED = "OVERPAYMENT_CREATED"
    NONE = "NONE"


class Worker(TypedDict):
    id: str
    full_name: str
    birth_year: int
    birth_month: int
    noncovered_pension_monthly_cents: int
    noncovered_pension_start_month: Optional[str]
    status: str
    death_date: Optional[str]
    fra_months: int
    age_months: int
    eligibility_year: int
    withdrawal_used: bool
    created_at: str
    updated_at: str
    version: int


class EarningsYear(TypedDict):
    id: str
    worker_id: str
    tax_year: int
    posted_earnings_cents: int
    noncovered_earnings_cents: int
    corrected: bool
    indexed_earnings_cents: int
    created_at: str
    updated_at: str
    version: int


class WageReport(TypedDict):
    # Append-only: carries only id + created_at (no updated_at, no version).
    id: str
    worker_id: str
    employer_name: str
    tax_year: int
    amount_cents: int
    covered_employment: bool
    posted_amount_cents: int
    status: str
    created_at: str


class CorrectionRequest(TypedDict):
    id: str
    worker_id: str
    tax_year: int
    claimed_earnings_cents: int
    evidence_type: str
    status: str
    statute_deadline: str
    decided_by: Optional[str]
    decided_at: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Relationship(TypedDict):
    id: str
    worker_id: str
    spouse_worker_id: str
    relationship_type: str
    marriage_date: str
    divorce_date: Optional[str]
    status: str
    marriage_months: int
    verified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BenefitClaim(TypedDict):
    id: str
    worker_id: str
    claim_type: str
    entitlement_month: str
    relationship_id: Optional[str]
    status: str
    claiming_age_months: int
    aime_cents: int
    pia_cents: int
    reduction_months: int
    drc_months: int
    monthly_benefit_cents: int
    total_paid_cents: int
    underpayment_credit_cents: int
    recovery_mode: str
    has_active_payee: bool
    suspended_since: Optional[str]
    decided_by: Optional[str]
    decided_at: Optional[str]
    denial_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BenefitPayment(TypedDict):
    id: str
    claim_id: str
    month: str
    gross_cents: int
    withheld_cents: int
    underpayment_credit_cents: int
    net_paid_cents: int
    paid_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class OverpaymentCase(TypedDict):
    id: str
    claim_id: str
    amount_cents: int
    period_start_month: str
    period_end_month: str
    reason: str
    status: str
    created_by: str
    recovered_cents: int
    remaining_cents: int
    waiver_grounds: Optional[str]
    waiver_decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayeeCase(TypedDict):
    id: str
    claim_id: str
    payee_name: str
    determination_basis: str
    status: str
    created_by: str
    decided_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecomputationEvent(TypedDict):
    # Append-only audit entry: carries only id + created_at (no updated_at, no version).
    id: str
    claim_id: str
    trigger: str
    old_pia_cents: int
    new_pia_cents: int
    old_monthly_benefit_cents: int
    new_monthly_benefit_cents: int
    retro_delta_cents: int
    resolution: str
    created_at: str
