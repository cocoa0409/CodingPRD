"""Domain types for the Lockbox Property Access API: status enums and entity shapes."""

from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    ASSOCIATION_ADMIN = "AssociationAdmin"
    MEMBER = "Member"
    SECURITY_AUDITOR = "SecurityAuditor"
    LOCKBOX_DEVICE = "LockboxDevice"


class AssociationPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class MembershipStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class MembershipEventType(str, Enum):
    RENEW = "RENEW"
    PLACE_ON_PROBATION = "PLACE_ON_PROBATION"
    SUSPEND = "SUSPEND"
    REINSTATE = "REINSTATE"
    EXPIRE = "EXPIRE"
    TERMINATE = "TERMINATE"


class ContractorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LockboxStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    ASSIGNED = "ASSIGNED"
    PLACED = "PLACED"
    MISSING = "MISSING"
    QUARANTINE = "QUARANTINE"
    RETIRED = "RETIRED"


class LockboxModel(str, Enum):
    LB_STD = "LB_STD"
    LB_PRO = "LB_PRO"


class LossType(str, Enum):
    LOST = "LOST"
    STOLEN = "STOLEN"


class ListingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_CONTRACT = "UNDER_CONTRACT"
    CLOSED = "CLOSED"
    WITHDRAWN = "WITHDRAWN"


class PlacementStatus(str, Enum):
    PLACED = "PLACED"
    REMOVAL_DUE = "REMOVAL_DUE"
    REMOVED = "REMOVED"
    DELINQUENT = "DELINQUENT"


class BillingStatus(str, Enum):
    NONE = "NONE"
    ACCRUED = "ACCRUED"
    SETTLED = "SETTLED"


class CredentialStatus(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class CredentialType(str, Enum):
    KEY_APP = "KEY_APP"
    KEY_FOB = "KEY_FOB"


class GrantType(str, Enum):
    ONE_DAY_MEMBER = "ONE_DAY_MEMBER"
    CONTRACTOR_WINDOW = "CONTRACTOR_WINDOW"
    INSPECTOR = "INSPECTOR"


class GrantStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    CONSUMED = "CONSUMED"


class AppointmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class CancelReason(str, Enum):
    AGENT_CANCELLED = "AGENT_CANCELLED"
    ACCESS_LOST = "ACCESS_LOST"


class ActorType(str, Enum):
    MEMBER = "MEMBER"
    CONTRACTOR = "CONTRACTOR"
    UNKNOWN = "UNKNOWN"


class AccessOutcome(str, Enum):
    GRANTED = "GRANTED"
    DENIED_BOX_MISSING = "DENIED_BOX_MISSING"
    DENIED_CREDENTIAL_INACTIVE = "DENIED_CREDENTIAL_INACTIVE"
    DENIED_OUTSIDE_WINDOW = "DENIED_OUTSIDE_WINDOW"
    DENIED_NO_CREDENTIAL = "DENIED_NO_CREDENTIAL"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    EVIDENCE_LOCKED = "EVIDENCE_LOCKED"
    CLOSED = "CLOSED"


class ReviewSeverity(str, Enum):
    LOW = "LOW"
    ELEVATED = "ELEVATED"
    CRITICAL = "CRITICAL"


class ChargeType(str, Enum):
    REPLACEMENT = "REPLACEMENT"
    LATE_REMOVAL = "LATE_REMOVAL"
    TEMP_CODE_OVERAGE = "TEMP_CODE_OVERAGE"


class ChargeStatus(str, Enum):
    PENDING = "PENDING"
    INVOICED = "INVOICED"
    PAID = "PAID"
    WAIVED = "WAIVED"
    VOID = "VOID"


class VariantApplied(str, Enum):
    FLAT_SCHEDULE = "FLAT_SCHEDULE"
    DEPRECIATED_BOOK = "DEPRECIATED_BOOK"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class RecoveryVariant(str, Enum):
    CLOSING_COHORT = "closing_cohort"
    REMOVAL_ACTIVITY = "removal_activity"


# --- Entity shapes -----------------------------------------------------------
# Resources below carry id / created_at / updated_at / version.


class Association(TypedDict):
    id: str
    name: str
    jurisdiction_code: str
    temp_code_daily_limit: int
    temp_code_overage_fee_cents: int
    removal_grace_days: int
    late_removal_daily_fee_cents: int
    late_removal_cap_cents: int
    credential_cap_per_member: int
    grant_buffer_minutes: int
    recovery_target_pct: float
    lockbox_total_count: int
    boxes_in_field_count: int
    unplaced_inventory_count: int
    missing_box_count: int
    active_placement_count: int
    delinquent_placement_count: int
    recovery_rate_pct: float
    posture: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    association_id: str
    full_name: str
    email: str
    dues_paid_through: str
    membership_status: str
    active_credential_count: int
    outstanding_balance_cents: int
    loss_report_count: int
    temp_codes_issued_today: int
    created_at: str
    updated_at: str
    version: int


class Contractor(TypedDict):
    id: str
    association_id: str
    company_name: str
    insurance_expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Lockbox(TypedDict):
    id: str
    association_id: str
    serial_number: str
    model: str
    replacement_cost_cents: int
    in_service_since: str
    status: str
    assigned_member_id: Optional[str]
    current_listing_id: Optional[str]
    loss_type: Optional[str]
    police_report_number: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict):
    id: str
    association_id: str
    listing_agent_id: str
    address_line: str
    mls_number: str
    concurrent_showing_limit: int
    status: str
    close_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LockboxPlacement(TypedDict):
    id: str
    lockbox_id: str
    listing_id: str
    placed_by_member_id: str
    placement_status: str
    billing_status: str
    placed_at: str
    removal_deadline: Optional[str]
    removed_at: Optional[str]
    late_days: Optional[int]
    on_time: Optional[bool]
    created_at: str
    updated_at: str
    version: int


class AccessCredential(TypedDict):
    id: str
    member_id: str
    credential_type: str
    expires_at: str
    status: str
    suspended_by_cascade: bool
    supersede_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccessGrant(TypedDict):
    id: str
    listing_id: str
    lockbox_id: str
    issued_by_member_id: str
    contractor_id: Optional[str]
    supersedes_grant_id: Optional[str]
    grant_type: str
    window_start: str
    window_end: str
    max_uses: int
    uses_count: int
    access_code: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ShowingAppointment(TypedDict):
    id: str
    listing_id: str
    showing_member_id: str
    window_start: str
    window_end: str
    status: str
    access_event_count: int
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class IncidentReview(TypedDict):
    id: str
    association_id: str
    listing_id: Optional[str]
    lockbox_id: Optional[str]
    window_start: str
    window_end: str
    opened_by_user_id: str
    closed_by_user_id: Optional[str]
    status: str
    event_count: int
    risk_score: float
    severity: str
    findings: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BillingCharge(TypedDict):
    id: str
    member_id: str
    lockbox_id: Optional[str]
    placement_id: Optional[str]
    charge_type: str
    amount_cents: int
    variant_applied: str
    basis: str
    status: str
    created_at: str
    updated_at: str
    version: int


# An access-log entry is append-only evidence: it carries id and created_at only —
# no updated_at and no version.
class AccessEvent(TypedDict):
    id: str
    lockbox_id: str
    credential_id: Optional[str]
    grant_id: Optional[str]
    listing_id: Optional[str]
    matched_appointment_id: Optional[str]
    incident_review_id: Optional[str]
    actor_type: str
    occurred_at: str
    outcome: str
    after_hours: bool
    risk_weight: float
    created_at: str
