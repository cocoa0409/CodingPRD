"""Domain types: entity TypedDicts, status enums, role enum.

Every resource in this PRD carries the four server-maintained common
properties (id, created_at, updated_at, version), so every TypedDict
below includes them.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CENTER_MANAGER = "CenterManager"
    VOLUNTEER = "Volunteer"
    GUEST = "Guest"
    ANONYMOUS = "Anonymous"


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------
class CenterPosture(str, Enum):
    CLOSED = "CLOSED"
    RESTRICTED = "RESTRICTED"
    OPEN = "OPEN"


class AgreementStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACTIVE = "ACTIVE"
    RENEWAL_DUE = "RENEWAL_DUE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class VolunteerStatus(str, Enum):
    APPLIED = "APPLIED"
    SCREENING = "SCREENING"
    CLEARED = "CLEARED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"


class ScreeningStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class ShiftStatus(str, Enum):
    OPEN = "OPEN"
    FILLED = "FILLED"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class GuestEligibility(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    EXPIRED = "EXPIRED"


class CheckInStatus(str, Enum):
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"


class BookingStatus(str, Enum):
    BOOKED = "BOOKED"
    COMPLETED = "COMPLETED"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"
    DISCARDED_EXPIRED = "DISCARDED_EXPIRED"


class EventStatus(str, Enum):
    PLANNED = "PLANNED"
    SECURITY_REVIEW = "SECURITY_REVIEW"
    SECURITY_APPROVED = "SECURITY_APPROVED"
    CONFIRMED = "CONFIRMED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class GrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


# ---------------------------------------------------------------------------
# Input enums
# ---------------------------------------------------------------------------
class ShiftRole(str, Enum):
    DESK = "DESK"
    KITCHEN = "KITCHEN"
    EVENTS = "EVENTS"
    FAMILY = "FAMILY"


class GuestCategory(str, Enum):
    ACTIVE_DUTY = "ACTIVE_DUTY"
    GUARD_RESERVE = "GUARD_RESERVE"
    DEPENDENT = "DEPENDENT"
    RETIREE = "RETIREE"
    VETERAN = "VETERAN"


class ServiceType(str, Enum):
    SLEEPING_AREA = "SLEEPING_AREA"
    SHOWER = "SHOWER"
    CONNECTIVITY = "CONNECTIVITY"
    FAMILY_ROOM = "FAMILY_ROOM"


class DonationCategory(str, Enum):
    FOOD = "FOOD"
    BEVERAGE = "BEVERAGE"
    SUPPLY = "SUPPLY"
    HYGIENE = "HYGIENE"


class EventKind(str, Enum):
    DEPLOYMENT = "DEPLOYMENT"
    HOMECOMING = "HOMECOMING"
    ENTERTAINMENT_TOUR = "ENTERTAINMENT_TOUR"


class ScreeningVerdict(str, Enum):
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry the common fields)
# ---------------------------------------------------------------------------
class ExpenseLedgerEntry(TypedDict):
    posted_at: str
    amount_cents: int
    description: str


class Center(TypedDict):
    id: str
    name: str
    airport_code: str
    occupancy_cap: int
    required_daily_confirmed_assignments: int
    posture: str
    current_occupancy: int
    coverage_ratio: float
    active_agreement_id: Optional[str]
    expense_ledger: List[ExpenseLedgerEntry]
    ops_run_count: int
    created_at: str
    updated_at: str
    version: int


class SiteAgreement(TypedDict):
    id: str
    center_id: str
    facility_space_sqft: int
    utilities_included: bool
    access_terms: str
    security_level: int
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict):
    id: str
    full_name: str
    email: str
    home_center_id: str
    status: str
    no_show_strikes: int
    total_hours: float
    created_at: str
    updated_at: str
    version: int


class BackgroundScreening(TypedDict):
    id: str
    volunteer_id: str
    status: str
    claimed_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict):
    id: str
    center_id: str
    start_at: str
    end_at: str
    role_required: str
    capacity: int
    confirmed_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ShiftAssignment(TypedDict):
    id: str
    shift_id: str
    volunteer_id: str
    status: str
    actual_hours: Optional[float]
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict):
    id: str
    full_name: str
    category: str
    verification_expires_on: str
    eligibility_status: str
    created_at: str
    updated_at: str
    version: int


class VisitCheckIn(TypedDict):
    id: str
    center_id: str
    guest_id: str
    checked_in_at: str
    checked_out_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceBooking(TypedDict):
    id: str
    center_id: str
    guest_id: str
    service_type: str
    start_at: str
    end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DonationLot(TypedDict):
    id: str
    center_id: str
    item_name: str
    category: str
    received_qty: int
    remaining_qty: int
    expiry_date: str
    declared_value_cents: int
    partner_match_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int
    # partner_name is optional on input; echo presence is not asserted.


class Event(TypedDict):
    id: str
    center_id: str
    kind: str
    name: str
    start_at: str
    end_at: str
    min_volunteers: int
    required_security_level: int
    talent_agreement_signed: bool
    event_budget_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FundingGrant(TypedDict):
    id: str
    center_id: str
    donor_name: str
    amount_cents: int
    spent_cents: int
    remaining_cents: int
    spend_by_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ExpenseResult(TypedDict):
    posted_cents: int
    debits: List[Dict[str, Any]]


class CostReport(TypedDict):
    center_id: str
    posture: str
    current_occupancy: int
    coverage_ratio: float
    month_expenses_cents: int
    month_visits: int
    cost_per_visit_actual_cents: Optional[int]
    cost_per_visit_loaded_cents: Optional[int]
    donation_value_total_cents: int
    partner_match_total_cents: int
