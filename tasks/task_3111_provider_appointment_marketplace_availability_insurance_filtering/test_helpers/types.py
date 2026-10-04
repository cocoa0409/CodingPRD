"""Domain types: entity TypedDicts, status enums, role enum.

All field names match PRD.md exactly. Entities flagged as append-only
(ContactEvent, LedgerEntry, VisitRecord) carry only id + created_at; all other
entities carry the full common set (id, created_at, updated_at, version).
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    PATIENT = "Patient"
    PROVIDER = "Provider"
    PRACTICE_STAFF = "PracticeStaff"
    OPS_ADMIN = "OpsAdmin"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class PracticeStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DELISTED = "DELISTED"


class ProviderStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DELISTED = "DELISTED"


class SlotStatus(str, Enum):
    OPEN = "OPEN"
    BOOKED = "BOOKED"
    CLOSED = "CLOSED"


class SlotCloseReason(str, Enum):
    PROVIDER_CLOSED = "PROVIDER_CLOSED"
    AUDIT_SWEEP = "AUDIT_SWEEP"
    PROVIDER_SUSPENDED = "PROVIDER_SUSPENDED"


class AppointmentTypeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class InsurancePlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class AttestationStatus(str, Enum):
    ATTESTED = "ATTESTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class BookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class AttributionStatus(str, Enum):
    ATTRIBUTED = "ATTRIBUTED"
    ORGANIC = "ORGANIC"


class CancelReason(str, Enum):
    PATIENT = "PATIENT"
    PRACTICE = "PRACTICE"
    RELIABILITY_GATE = "RELIABILITY_GATE"


class ChargeStatus(str, Enum):
    BILLABLE = "BILLABLE"
    INVOICED = "INVOICED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    REFUNDED = "REFUNDED"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class LedgerEntryType(str, Enum):
    CHARGE_FEE = "CHARGE_FEE"
    TIER_DISCOUNT = "TIER_DISCOUNT"
    DISPUTE_CREDIT = "DISPUTE_CREDIT"
    SUBSCRIPTION_FEE = "SUBSCRIPTION_FEE"
    PAYMENT = "PAYMENT"
    WRITE_OFF = "WRITE_OFF"


class ComplaintStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_DISMISSED = "RESOLVED_DISMISSED"


class ComplaintType(str, Enum):
    INSURANCE_MISMATCH = "INSURANCE_MISMATCH"
    DIRECTORY_INACCURACY = "DIRECTORY_INACCURACY"
    OTHER = "OTHER"


class ComplaintOutcome(str, Enum):
    UPHOLD = "UPHOLD"
    DISMISS = "DISMISS"


class ReviewStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    FLAGGED = "FLAGGED"
    REMOVED = "REMOVED"


class AuditCaseScope(str, Enum):
    AVAILABILITY = "AVAILABILITY"
    INSURANCE = "INSURANCE"
    FULL = "FULL"


class AuditCaseSeverity(str, Enum):
    CLEAN = "CLEAN"
    WARN = "WARN"
    CRITICAL = "CRITICAL"


class AuditCaseStatus(str, Enum):
    OPEN = "OPEN"
    FINDINGS_OPEN = "FINDINGS_OPEN"
    CLOSED_CLEAN = "CLOSED_CLEAN"
    CLOSED = "CLOSED"


class AuditFindingType(str, Enum):
    TIME_TRAVEL_SLOT = "TIME_TRAVEL_SLOT"
    INSURANCE_STALE = "INSURANCE_STALE"


class BillingMode(str, Enum):
    PER_BOOKING = "PER_BOOKING"
    SUBSCRIPTION = "SUBSCRIPTION"


class ContactChannel(str, Enum):
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    PORTAL = "PORTAL"
    WALKIN = "WALKIN"


class StrikeKind(str, Enum):
    NO_SHOW = "NO_SHOW"
    LATE_CANCEL = "LATE_CANCEL"


# ---------------------------------------------------------------------------
# Entity TypedDicts (common_fields: true — id + created_at + updated_at + version)
# ---------------------------------------------------------------------------

class Practice(TypedDict):
    id: str
    name: str
    timezone: str
    billing_mode: str
    subscription_fee_cents: int
    new_patient_lead_time_hours: int
    existing_patient_lead_time_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict):
    id: str
    practice_id: str
    display_name: str
    specialty: str
    lead_time_override_hours: Optional[int]
    insurance_mismatch_count: int
    bookable_in_directory: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Slot(TypedDict):
    id: str
    provider_id: str
    start_at: str
    end_at: str
    status: str
    close_reason: Optional[str]
    current_booking_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AppointmentType(TypedDict):
    id: str
    provider_id: str
    code: str
    display_name: str
    duration_minutes: int
    booked_copay_cents: int
    accepts_new_patients: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class InsurancePlan(TypedDict):
    id: str
    carrier: str
    plan_name: str
    plan_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Attestation(TypedDict):
    id: str
    provider_id: str
    plan_id: str
    effective_from: str
    effective_to: str
    status: str
    verified_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Strike(TypedDict):
    epoch: int
    magnitude: int
    kind: str


class Patient(TypedDict):
    id: str
    full_name: str
    email: str
    plan_id: Optional[str]
    reliability_score: int
    provisional_score: int
    strikes: List[Strike]
    recovery_count: int
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    slot_id: str
    patient_id: str
    provider_id: str
    practice_id: str
    appointment_type_id: str
    insurance_plan_id: Optional[str]
    start_at: str
    end_at: str
    booked_copay_cents: int
    is_new_patient: bool
    attribution_status: str
    late_cancel: bool
    cancel_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Charge(TypedDict):
    id: str
    booking_id: str
    practice_id: str
    invoice_id: Optional[str]
    gross_cents: int
    marketplace_fee_cents: int
    processing_cents: int
    net_to_practice_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    practice_id: str
    period: str
    charge_count: int
    fee_total_cents: int
    discount_tier: float
    discount_cents: int
    amount_due_cents: int
    payout_provisional_cents: int
    payout_final_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict):
    id: str
    booking_id: str
    patient_id: str
    provider_id: str
    complaint_type: str
    description: Optional[str]
    response: Optional[str]
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Review(TypedDict):
    id: str
    booking_id: str
    patient_id: str
    provider_id: str
    rating: int
    text: Optional[str]
    flag_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditFinding(TypedDict):
    finding_index: int
    finding_type: str
    ref_id: str
    resolved: bool


class AuditCase(TypedDict):
    id: str
    provider_id: str
    scope: str
    sampled_count: int
    mismatch_count: int
    mismatch_rate: float
    severity: str
    findings: List[AuditFinding]
    status: str
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# Append-only entities (common_fields: false — ONLY id + created_at)
# ---------------------------------------------------------------------------

class ContactEvent(TypedDict):
    id: str
    patient_id: str
    practice_id: str
    provider_id: Optional[str]
    contacted_at: str
    channel: str
    created_at: str


class LedgerEntry(TypedDict):
    id: str
    invoice_id: str
    charge_id: Optional[str]
    entry_type: str
    amount_cents: int
    note: Optional[str]
    created_at: str


class VisitRecord(TypedDict):
    id: str
    booking_id: str
    provider_id: str
    patient_id: str
    completed_at: str
    verification: str
    created_at: str
