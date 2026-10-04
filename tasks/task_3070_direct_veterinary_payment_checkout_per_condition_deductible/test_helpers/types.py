"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD resource model exactly:
- TerritoryRateFiling, Hospital, Policy, PolicyCondition, Claim, Payment,
  ClaimAppeal carry the full common-field set (id, created_at, updated_at,
  version).
- MedicalRecord and ReconciliationReport carry ONLY id and created_at
  (no updated_at, no version) per PRD section 2.4.
"""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    RATE_FILING_ADMIN = "RateFilingAdmin"
    HOSPITAL_STAFF = "HospitalStaff"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"
    PET_OWNER = "PetOwner"


class FilingStatus(str, Enum):
    DRAFT = "DRAFT"
    FILED = "FILED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class HospitalStatus(str, Enum):
    APPLIED = "APPLIED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class EnrollmentStatus(str, Enum):
    INJURY_WAITING = "INJURY_WAITING"
    ILLNESS_WAITING = "ILLNESS_WAITING"
    FULLY_ACTIVE = "FULLY_ACTIVE"


class LifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    LAPSED = "LAPSED"


class ClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    PREEXISTING_REVIEW = "PREEXISTING_REVIEW"
    ADJUDICATED = "ADJUDICATED"
    DENIED = "DENIED"
    PAID = "PAID"
    PAYMENT_FAILED = "PAYMENT_FAILED"
    SETTLED = "SETTLED"
    REOPENED = "REOPENED"


class ClaimType(str, Enum):
    INJURY = "INJURY"
    ILLNESS = "ILLNESS"


class LineCategory(str, Enum):
    TREATMENT = "TREATMENT"
    EXAM_FEE = "EXAM_FEE"
    TAX = "TAX"
    OTHER_EXCLUDED = "OTHER_EXCLUDED"


class RecordType(str, Enum):
    EXAM = "EXAM"
    LAB = "LAB"
    IMAGING = "IMAGING"
    PROCEDURE = "PROCEDURE"
    PRESCRIPTION = "PRESCRIPTION"


class PaymentStatus(str, Enum):
    INITIATED = "INITIATED"
    SETTLED = "SETTLED"
    FAILED = "FAILED"
    REVERSED = "REVERSED"


class LedgerStatus(str, Enum):
    POSTED = "POSTED"
    PENDING_POST = "PENDING_POST"
    EXCLUDED = "EXCLUDED"


class PaymentKind(str, Enum):
    DIRECT_PAY = "DIRECT_PAY"
    CLAWBACK = "CLAWBACK"


class AppealStatus(str, Enum):
    OPEN = "OPEN"
    RECORDS_REQUESTED = "RECORDS_REQUESTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class ReportStatus(str, Enum):
    GENERATED = "GENERATED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISPUTED = "DISPUTED"


class Species(str, Enum):
    DOG = "DOG"
    CAT = "CAT"


class TerritoryRateFiling(TypedDict, total=False):
    id: str
    territory_code: str
    state_code: str
    species: str
    base_monthly_premium_cents: int
    age_band_multipliers: dict
    filing_effective_date: str
    regulator_reference: str
    status: str
    filed_at: Optional[str]
    effective_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Hospital(TypedDict, total=False):
    id: str
    legal_name: str
    territory_code: str
    bank_account_ref: str
    checkout_software_version: str
    training_completed_at: Optional[str]
    status: str
    running_ledger_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Policy(TypedDict, total=False):
    id: str
    owner_name: str
    pet_name: str
    species: str
    breed: str
    pet_date_of_birth: str
    territory_code: str
    coverage_start: str
    per_condition_deductible_cents: int
    reimbursement_rate: float
    enrollment_status: str
    lifecycle_status: str
    current_monthly_premium_cents: int
    filed_base_cents: int
    applied_filing_id: str
    next_birthday: str
    injury_waiting_end: str
    illness_waiting_end: str
    created_at: str
    updated_at: str
    version: int


class MedicalRecord(TypedDict, total=False):
    # Carries ONLY id + created_at (no updated_at, no version).
    id: str
    policy_id: str
    hospital_id: str
    record_type: str
    recorded_at: str
    diagnosis_code: str
    notes: str
    appeal_id: Optional[str]
    created_at: str


class PolicyCondition(TypedDict, total=False):
    id: str
    policy_id: str
    condition_code: str
    preexisting: bool
    deductible_target_cents: int
    deductible_accumulated_cents: int
    lifetime_reimbursed_cents: int
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    policy_id: str
    hospital_id: str
    visit_date: str
    claim_type: str
    status: str
    total_invoice_cents: int
    eligible_cents: int
    deductible_applied_cents: int
    reimbursement_cents: int
    member_responsibility_cents: int
    adjudicated_at: Optional[str]
    denial_reason: Optional[str]
    payment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClaimLine(TypedDict, total=False):
    # Append-only line: no updated_at, no version.
    id: str
    claim_id: str
    seq: int
    description: str
    amount_cents: int
    category: str
    condition_code: Optional[str]
    eligible_amount_cents: int
    policy_condition_id: Optional[str]
    deductible_applied_cents: int
    reimbursement_cents: int
    created_at: str


class Payment(TypedDict, total=False):
    id: str
    claim_id: str
    hospital_id: str
    amount_cents: int
    kind: str
    status: str
    ledger_status: str
    idempotency_key: str
    reverses_payment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClaimAppeal(TypedDict, total=False):
    id: str
    claim_id: str
    opened_by: str
    reason_code: str
    original_adjuster_id: str
    status: str
    records_due_at: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReconciliationReport(TypedDict, total=False):
    # Carries ONLY id + created_at (no updated_at, no version).
    id: str
    hospital_id: str
    period_start: str
    period_end: str
    expected_cents: int
    actual_cents: int
    discrepancy_cents: int
    status: str
    created_at: str
