"""Domain types: entity TypedDicts, status enums and the role enum.

Field names are taken verbatim from the PRD so that tests and fixtures never
abbreviate a field. Every one of the fourteen entities carries the full common
field set (`id`, `created_at`, `updated_at`, `version`).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────

class UserRole(str, Enum):
    OPS_ADMIN = "OpsAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CLINICIAN = "Clinician"
    PATIENT = "Patient"
    PAYROLL_SERVICE = "PayrollService"
    ANONYMOUS = "Anonymous"


# ─── Clinician ────────────────────────────────────────

class LicenseType(str, Enum):
    LCSW = "LCSW"
    LMFT = "LMFT"
    LPC = "LPC"
    LMHC = "LMHC"
    PSY_D = "PSY_D"
    PHD = "PHD"


class ClinicianStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    CREDENTIALING = "CREDENTIALING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    OFFBOARDING = "OFFBOARDING"
    OFFBOARDED = "OFFBOARDED"


class BillingPosture(str, Enum):
    BILLABLE = "BILLABLE"
    GATED = "GATED"
    FROZEN = "FROZEN"


# ─── License ──────────────────────────────────────────

class LicenseVerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


# ─── MalpracticePolicy ────────────────────────────────

class MalpracticePolicyStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"


# ─── Payer ────────────────────────────────────────────

class PayerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED_AT_PAYER = "SUSPENDED_AT_PAYER"
    TERMINATED = "TERMINATED"


# ─── PayerEnrollment ──────────────────────────────────

class EnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    EFFECTIVE = "EFFECTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    REJECTED = "REJECTED"


# ─── PatientClient ────────────────────────────────────

class BenefitStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    STALE = "STALE"


class VerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    STALE = "STALE"
    FAILED = "FAILED"


# ─── Session ──────────────────────────────────────────

class SessionStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class SessionBillingState(str, Enum):
    UNBILLED = "UNBILLED"
    CLAIM_SUBMITTED = "CLAIM_SUBMITTED"
    PAYER_PAID = "PAYER_PAID"
    DENIED = "DENIED"
    WRITTEN_OFF = "WRITTEN_OFF"


class SessionModality(str, Enum):
    VIDEO = "VIDEO"
    PHONE = "PHONE"
    IN_PERSON = "IN_PERSON"


# ─── SessionNote ──────────────────────────────────────

class SessionNoteStatus(str, Enum):
    DRAFT = "DRAFT"
    SIGNED = "SIGNED"
    LOCKED = "LOCKED"


# ─── Claim ────────────────────────────────────────────

class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    PAID = "PAID"
    DENIED = "DENIED"
    REPROCESSING = "REPROCESSING"
    WRITTEN_OFF = "WRITTEN_OFF"


class DenialCode(str, Enum):
    TIMELY_FILING = "TIMELY_FILING"
    NOT_COVERED = "NOT_COVERED"
    MISSING_DOCUMENTATION = "MISSING_DOCUMENTATION"
    AUTHORIZATION_REQUIRED = "AUTHORIZATION_REQUIRED"
    DUPLICATE = "DUPLICATE"


# ─── PayoutBatch / PayoutLine ─────────────────────────

class PayoutSchedule(str, Enum):
    WEEKLY = "WEEKLY"
    BIWEEKLY = "BIWEEKLY"
    SEMIMONTHLY = "SEMIMONTHLY"


class PayoutBatchStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    PAID = "PAID"
    RECONCILED = "RECONCILED"
    SKIPPED = "SKIPPED"


class PayoutLineStatus(str, Enum):
    PENDING = "PENDING"
    PAID = "PAID"
    CLAWED_BACK = "CLAWED_BACK"
    VOIDED = "VOIDED"


class PayoutBasis(str, Enum):
    SCHEDULED = "SCHEDULED"
    CASH_BASIS = "CASH_BASIS"


# ─── ContinuityPlan ───────────────────────────────────

class ContinuityPlanStatus(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    ESCALATED = "ESCALATED"
    COMPLETED = "COMPLETED"


class ContinuityReason(str, Enum):
    OFFBOARDING = "OFFBOARDING"
    CASELOAD_REBALANCE = "CASELOAD_REBALANCE"
    CLINICAL_CONFLICT = "CLINICAL_CONFLICT"


# ─── Entity shapes ────────────────────────────────────

class AvailabilityBlock(TypedDict):
    weekday: int
    start_minute: int
    end_minute: int


class Clinician(TypedDict, total=False):
    id: str
    full_name: str
    license_type: str
    primary_state: str
    specialty_tags: List[str]
    weekly_caseload_target: int
    availability_blocks: List[AvailabilityBlock]
    onboarded_at: str
    status: str
    billing_posture: str
    active_patient_count: int
    open_slot_count: int
    enrolled_payer_count: int
    payout_balance_cents: int
    offboarding_requested_on: Optional[str]
    continuity_plan_count: int
    cash_basis_opt_in: bool
    pending_clawback_residual_cents: int
    created_at: str
    updated_at: str
    version: int


class License(TypedDict, total=False):
    id: str
    clinician_id: str
    license_number: str
    license_type: str
    issuing_state: str
    expires_on: str
    telehealth_eligible: bool
    verification_status: str
    verified_at: Optional[str]
    verified_by_user_id: Optional[str]
    verification_attempts: int
    created_at: str
    updated_at: str
    version: int


class MalpracticePolicy(TypedDict, total=False):
    id: str
    clinician_id: str
    carrier_name: str
    coverage_cents: int
    effective_on: str
    expires_on: str
    tail_coverage: bool
    policy_status: str
    created_at: str
    updated_at: str
    version: int


class Payer(TypedDict, total=False):
    id: str
    payer_name: str
    payer_code: str
    delegated_credentialing: bool
    min_malpractice_coverage_cents: int
    timely_filing_days: int
    credentialing_sla_days: int
    allowed_cpt_codes: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PayerRate(TypedDict, total=False):
    id: str
    payer_id: str
    rate_set_version: int
    license_type: str
    geography: str
    cpt_code: str
    rate_cents: int
    effective_from: str
    effective_to: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayerEnrollment(TypedDict, total=False):
    id: str
    clinician_id: str
    payer_id: str
    delegated: bool
    effective_from: str
    effective_to: Optional[str]
    status: str
    effective_window_days: Optional[int]
    rate_set_version_pinned: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PatientClient(TypedDict, total=False):
    id: str
    full_name: str
    member_id: str
    payer_id: str
    plan_code: str
    state_code: str
    deductible_cents: int
    coinsurance_rate: float
    oop_max_cents: int
    oop_met_cents: int
    benefit_status: str
    matched_clinician_id: Optional[str]
    swap_requested: bool
    visit_count_year: int
    created_at: str
    updated_at: str
    version: int


class BenefitVerification(TypedDict, total=False):
    id: str
    patient_id: str
    payer_id: str
    deductible_remaining_cents: int
    coinsurance_rate: float
    copay_cents: int
    oop_remaining_cents: int
    status: str
    verified_at: str
    quoted_cost_share_cents: int
    created_at: str
    updated_at: str
    version: int


class Session(TypedDict, total=False):
    id: str
    clinician_id: str
    patient_id: str
    scheduled_start: str
    scheduled_end: str
    cpt_code: str
    modality: str
    status: str
    billing_state: str
    quoted_cost_share_cents: Optional[int]
    slot_consumed: bool
    claim_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SessionNote(TypedDict, total=False):
    id: str
    session_id: str
    diagnosis_code: str
    duration_minutes: int
    cpt_code: str
    narrative: str
    status: str
    signed_at: Optional[str]
    signer_clinician_id: Optional[str]
    note_version: int
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    session_id: str
    payer_id: str
    clinician_id: str
    submitted_on: str
    billed_cents: int
    allowed_cents: int
    patient_resp_cents: int
    payer_paid_cents: int
    claim_status: str
    denial_code: Optional[str]
    recovery_deadline: Optional[str]
    resubmission_count: int
    assigned_payout_line_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayoutBatch(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    schedule: str
    status: str
    total_gross_cents: int
    total_adjustment_cents: int
    total_net_cents: int
    line_count: int
    created_by_user_id: str
    supersedes_batch_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PayoutLine(TypedDict, total=False):
    id: str
    payout_batch_id: str
    clinician_id: str
    session_ids: List[str]
    claim_ids: List[str]
    gross_cents: int
    adjustment_cents: int
    net_cents: int
    line_status: str
    basis: str
    rate_set_version_used: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ContinuityPlan(TypedDict, total=False):
    id: str
    clinician_id: str
    patient_id: str
    successor_clinician_id: Optional[str]
    reassignment_deadline: str
    status: str
    reason: str
    created_at: str
    updated_at: str
    version: int