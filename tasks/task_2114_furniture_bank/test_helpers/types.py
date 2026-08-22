"""Domain types for the Furniture Bank Distribution API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.  Every persisted resource in this system carries the same four
common properties (`id`, `created_at`, `updated_at`, `version`) with no
exceptions, so every TypedDict below lists all four.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Role enum (PRD §2.1) ──────────────────────────────────────────────

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CASE_MANAGER = "CaseManager"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    WAREHOUSE_LEAD = "WarehouseLead"
    DISPATCH_PLANNER = "DispatchPlanner"
    VOLUNTEER = "Volunteer"


# ─── Shared value enums ────────────────────────────────────────────────

class County(str, Enum):
    NORTH = "NORTH"
    CENTRAL = "CENTRAL"
    SOUTH = "SOUTH"


class GoodsCategory(str, Enum):
    BED = "BED"
    SOFA = "SOFA"
    CRIB = "CRIB"
    TABLE_SET = "TABLE_SET"
    DRESSER = "DRESSER"
    KITCHEN_KIT = "KITCHEN_KIT"
    LINENS = "LINENS"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


# ─── State enums ───────────────────────────────────────────────────────

class AgencyStanding(str, Enum):
    GOOD = "GOOD"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class ClientStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"


class BedBugStatus(str, Enum):
    CLEAR = "CLEAR"
    CONFIRMED = "CONFIRMED"
    REMEDIATED = "REMEDIATED"


class ReferralStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    FULFILLED = "FULFILLED"


class ReferralUrgency(str, Enum):
    ROUTINE = "ROUTINE"
    PRIORITY = "PRIORITY"
    EMERGENCY = "EMERGENCY"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    RETURN = "RETURN"
    DENY = "DENY"


class VoucherStatus(str, Enum):
    ISSUED = "ISSUED"
    PARTIALLY_ALLOCATED = "PARTIALLY_ALLOCATED"
    ALLOCATED = "ALLOCATED"
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class VoucherFeeStatus(str, Enum):
    PENDING = "PENDING"
    WAIVED = "WAIVED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    WRITTEN_OFF = "WRITTEN_OFF"


class FeeBasis(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class FeeSettlementAction(str, Enum):
    WAIVE = "WAIVE"
    INVOICE = "INVOICE"
    RECORD_PAYMENT = "RECORD_PAYMENT"
    WRITE_OFF = "WRITE_OFF"


class VoucherLineStatus(str, Enum):
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"


class DonationOfferStatus(str, Enum):
    OFFERED = "OFFERED"
    TRIAGED = "TRIAGED"
    PICKUP_SCHEDULED = "PICKUP_SCHEDULED"
    INSPECTED = "INSPECTED"
    QUARANTINED = "QUARANTINED"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"


class DonationItemDecision(str, Enum):
    PENDING = "PENDING"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class RejectReason(str, Enum):
    RECALLED_CRIB = "RECALLED_CRIB"
    CONDITION_BELOW_MIN = "CONDITION_BELOW_MIN"
    SOFT_SURFACE_RISK = "SOFT_SURFACE_RISK"
    CAPACITY = "CAPACITY"


class InventoryItemStatus(str, Enum):
    QUARANTINED = "QUARANTINED"
    AVAILABLE = "AVAILABLE"
    RESERVED = "RESERVED"
    STAGED = "STAGED"
    DELIVERED = "DELIVERED"
    DISPOSED = "DISPOSED"


class DeliveryRunStatus(str, Enum):
    PLANNED = "PLANNED"
    CREWED = "CREWED"
    DISPATCHED = "DISPATCHED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class DeliveryStopStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    NO_SHOW = "NO_SHOW"
    REFUSED = "REFUSED"
    CANCELLED = "CANCELLED"


class StopOutcome(str, Enum):
    DELIVERED = "DELIVERED"
    NO_SHOW = "NO_SHOW"
    REFUSED = "REFUSED"


class CrewAssignmentStatus(str, Enum):
    INVITED = "INVITED"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    RELEASED = "RELEASED"
    NO_SHOW = "NO_SHOW"


class CrewRole(str, Enum):
    DRIVER = "DRIVER"
    LIFTER = "LIFTER"


class CrewResponse(str, Enum):
    CONFIRM = "CONFIRM"
    DECLINE = "DECLINE"
    WITHDRAW = "WITHDRAW"


class WaitlistEntryStatus(str, Enum):
    WAITING = "WAITING"
    PROMOTED = "PROMOTED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


# ─── Entity shapes ─────────────────────────────────────────────────────

class PartnerAgency(TypedDict):
    id: str
    name: str
    county: str
    quarterly_voucher_quota: int
    quota_used: int
    quota_epoch: int
    standing: str
    no_show_credits_owed_cents: int
    created_at: str
    updated_at: str
    version: int


class Client(TypedDict):
    id: str
    agency_id: str
    household_size: int
    county: str
    has_infant: bool
    bed_bug_status: str
    bed_bug_confirmed_at: Optional[str]
    no_show_strikes: int
    delivery_ban_until: Optional[str]
    lifetime_vouchers_delivered: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    client_id: str
    agency_id: str
    requested_categories: List[str]
    urgency: str
    home_visit_completed: bool
    bed_bug_attestation: bool
    status: str
    revision_count: int
    priority_score: float
    approved_at: Optional[str]
    expires_at: Optional[str]
    approved_epoch: Optional[int]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Voucher(TypedDict):
    id: str
    referral_id: str
    status: str
    fee_status: str
    gross_fee_cents: int
    subsidy_cents: int
    client_due_cents: int
    fee_basis: Optional[str]
    fill_ratio: float
    amount_paid_cents: int
    created_at: str
    updated_at: str
    version: int


class VoucherLine(TypedDict):
    id: str
    voucher_id: str
    category: str
    quantity_requested: int
    min_condition: str
    quantity_allocated: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DonationOffer(TypedDict):
    id: str
    donor_name: str
    donor_phone: str
    pickup_county: str
    pickup_window_start: str
    pickup_window_end: str
    truck_id: Optional[str]
    status: str
    accepted_item_count: int
    rejected_item_count: int
    declared_soft_ratio: float
    bed_bug_risk_score: float
    inspector_user_id: Optional[str]
    quarantine_started_at: Optional[str]
    quarantine_release_due_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DonationItem(TypedDict):
    id: str
    offer_id: str
    category: str
    declared_condition: str
    soft_surface: bool
    cubic_feet: float
    decision: str
    reject_reason: Optional[str]
    graded_condition: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InventoryItem(TypedDict):
    id: str
    donation_item_id: str
    category: str
    condition: str
    cubic_feet: float
    status: str
    reserved_for_voucher_line_id: Optional[str]
    available_since: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Truck(TypedDict):
    id: str
    label: str
    capacity_cubic_feet: float
    home_county: str
    crew_minimum: int
    bed_bug_lockout_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeliveryRun(TypedDict):
    id: str
    truck_id: str
    service_date: str
    window_start: str
    window_end: str
    county: str
    rescheduled_from_run_id: Optional[str]
    status: str
    load_cubic_feet: float
    confirmed_crew_count: int
    has_confirmed_driver: bool
    stop_count: int
    created_at: str
    updated_at: str
    version: int


class DeliveryStop(TypedDict):
    id: str
    run_id: str
    voucher_id: str
    sequence: int
    status: str
    pest_observed_at_residence: bool
    chargeback_cents: int
    outcome_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict):
    id: str
    name: str
    county: str
    lift_certified: bool
    reliability_score: float
    assigned_hours_month: float
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict):
    id: str
    run_id: str
    volunteer_id: str
    role_on_crew: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WaitlistEntry(TypedDict):
    id: str
    voucher_line_id: str
    client_id: str
    category: str
    county: str
    quantity_unmet: int
    priority_score: float
    waiting_since: str
    status: str
    created_at: str
    updated_at: str
    version: int
