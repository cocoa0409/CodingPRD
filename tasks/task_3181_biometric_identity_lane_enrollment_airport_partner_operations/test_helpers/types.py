"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    MEMBER = "Member"
    AMBASSADOR = "Ambassador"
    OPS_ADMIN = "OpsAdmin"
    PARTNER_MANAGER = "PartnerManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    VENUE_OPS = "VenueOps"


class MemberStatus(str, Enum):
    PENDING_ENROLLMENT = "PENDING_ENROLLMENT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class VerificationLevel(str, Enum):
    NONE = "NONE"
    BIOMETRIC_ID = "BIOMETRIC_ID"
    FEDERAL_TRUSTED = "FEDERAL_TRUSTED"


class EnrollmentStatus(str, Enum):
    DRAFT = "DRAFT"
    DOCUMENT_VERIFIED = "DOCUMENT_VERIFIED"
    BIOMETRIC_CAPTURED = "BIOMETRIC_CAPTURED"
    FRAUD_REVIEW = "FRAUD_REVIEW"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class KioskStatus(str, Enum):
    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class EnrollmentCenterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AmbassadorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AirportStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class LaneStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    MAINTENANCE = "MAINTENANCE"
    CLOSED = "CLOSED"


class VenueStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class VenueEventStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELLED = "CANCELLED"


class Plan(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    FAMILY = "FAMILY"


class FamilyGroupStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISSOLVED = "DISSOLVED"


class DiscountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    SUSPENDED = "SUSPENDED"


class EscortStatus(str, Enum):
    PENDING = "PENDING"
    ESCORTED = "ESCORTED"
    EXPIRED = "EXPIRED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    INVESTIGATING = "INVESTIGATING"
    RESOLVED_CLEAR = "RESOLVED_CLEAR"
    RESOLVED_CONFIRMED = "RESOLVED_CONFIRMED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    PAID = "PAID"


class InvoiceStatus(str, Enum):
    DUE = "DUE"
    PAID = "PAID"
    FAILED = "FAILED"
    VOID = "VOID"


class Member(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    date_of_birth: str
    status: str
    verification_level: str
    subscription_id: Optional[str]
    family_group_id: Optional[str]
    document_reject_count_90d: int
    risk_score: int
    deletion_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    member_id: str
    site_type: str
    site_id: str
    document_type: str
    document_number: str
    document_expiry: str
    biometric_capture_ok: bool
    status: str
    is_re_enrollment: bool
    risk_flags: list
    superseded_by_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Kiosk(TypedDict, total=False):
    id: str
    airport_id: str
    code: str
    status: str
    activated_at: Optional[str]
    consecutive_capture_failures: int
    created_at: str
    updated_at: str
    version: int


class EnrollmentCenter(TypedDict, total=False):
    id: str
    airport_id: str
    name: str
    status: str
    ambassador_capacity: int
    created_at: str
    updated_at: str
    version: int


class Ambassador(TypedDict, total=False):
    id: str
    airport_id: str
    display_name: str
    employee_ref: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Airport(TypedDict, total=False):
    id: str
    iata_code: str
    name: str
    city: str
    state_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PartnerAgreement(TypedDict, total=False):
    id: str
    airport_id: str
    rev_share_rate: float
    subscription_share_rate: float
    monthly_minimum_cents: int
    federal_integration: bool
    staffing_footprint_seats: int
    term_months: int
    status: str
    effective_from: str
    effective_to: Optional[str]
    lane_capacity: int
    created_at: str
    updated_at: str
    version: int


class Lane(TypedDict, total=False):
    id: str
    airport_id: str
    agreement_id: str
    terminal: str
    position_index: int
    open_time: str
    close_time: str
    capacity_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict, total=False):
    id: str
    name: str
    venue_type: str
    city: str
    state_code: str
    access_rule_mode: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VenueEvent(TypedDict, total=False):
    id: str
    venue_id: str
    name: str
    start_time: str
    end_time: str
    buffer_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    member_id: str
    plan: str
    price_cents: int
    billing_cycle_day: int
    partner_discount_id: Optional[str]
    status: str
    current_period_start: Optional[str]
    current_period_end: Optional[str]
    pending_plan: Optional[str]
    past_due_since: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FamilyGroup(TypedDict, total=False):
    id: str
    primary_subscription_id: str
    slots_total: int
    slots_used: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartnerDiscount(TypedDict, total=False):
    id: str
    airport_id: str
    code: str
    percent_off: int
    max_redemptions: int
    redemptions_used: int
    status: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class LaneVerification(TypedDict, total=False):
    id: str
    member_id: str
    lane_id: str
    ambassador_id: str
    verified_at: str
    federal_program: bool
    escort_status: str
    outcome: str
    reject_reason: Optional[str]
    version_confirmed: int
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class VenueAccessEvent(TypedDict, total=False):
    id: str
    venue_id: str
    member_id: str
    accessed_at: str
    outcome: str
    reject_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IdentityDispute(TypedDict, total=False):
    id: str
    member_id: str
    enrollment_id: str
    reason: str
    status: str
    resolved_by: Optional[str]
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BiometricRetentionLog(TypedDict, total=False):
    # Append-only audit rows: carry id + created_at only (no updated_at, no version).
    id: str
    member_id: str
    action: str
    actor_user_id: str
    note: Optional[str]
    created_at: str


class AgreementSettlement(TypedDict, total=False):
    id: str
    agreement_id: Optional[str]
    venue_id: Optional[str]
    period_start: str
    period_end: str
    attributable_mrr_cents: int
    verification_revenue_cents: int
    events_count: int
    fee_cents: int
    calculation_variant: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SubscriptionInvoice(TypedDict, total=False):
    id: str
    subscription_id: str
    period_start: str
    period_end: str
    amount_cents: int
    status: str
    attempt_count: int
    due_at: str
    created_at: str
    updated_at: str
    version: int
