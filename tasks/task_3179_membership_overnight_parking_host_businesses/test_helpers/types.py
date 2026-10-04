"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class HostCategory(str, Enum):
    WINERY = "WINERY"
    FARM = "FARM"
    BREWERY = "BREWERY"
    ATTRACTION = "ATTRACTION"


class OnboardingStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    REJECTED = "REJECTED"


class Posture(str, Enum):
    OPEN = "OPEN"
    LIMITED = "LIMITED"
    UNAVAILABLE = "UNAVAILABLE"
    SUSPENDED = "SUSPENDED"


class SiteClass(str, Enum):
    PULL_THROUGH = "PULL_THROUGH"
    BACK_IN = "BACK_IN"


class ElectricServiceCode(str, Enum):
    NONE = "NONE"
    ELECTRIC_30A = "ELECTRIC_30A"
    ELECTRIC_50A = "ELECTRIC_50A"


class PlanTier(str, Enum):
    CLASSIC = "CLASSIC"
    PLUS = "PLUS"
    PREMIER = "PREMIER"


class SubscriptionStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    CANCELLED = "CANCELLED"


class RemovalStatus(str, Enum):
    NONE = "NONE"
    REMOVED = "REMOVED"


class VehicleClass(str, Enum):
    CLASS_A = "CLASS_A"
    CLASS_B = "CLASS_B"
    CLASS_C = "CLASS_C"
    FIFTH_WHEEL = "FIFTH_WHEEL"
    TRAVEL_TRAILER = "TRAVEL_TRAILER"
    CONVERSION_VAN = "CONVERSION_VAN"


class WindowKind(str, Enum):
    SEASONAL = "SEASONAL"
    EVENT = "EVENT"


class WindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class StayStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    DECLINED = "DECLINED"
    CANCELLED = "CANCELLED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    NO_SHOW = "NO_SHOW"


class StayOrigin(str, Enum):
    MEMBER_INITIATED = "MEMBER_INITIATED"
    HOST_INITIATED = "HOST_INITIATED"


class ReviewAuthorKind(str, Enum):
    HOST = "HOST"
    MEMBER = "MEMBER"


class ReviewStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    WITHDRAWN = "WITHDRAWN"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    SEVERE = "SEVERE"


class IncidentOrigin(str, Enum):
    MEMBER_REPORT = "MEMBER_REPORT"
    STAFF_FILING = "STAFF_FILING"
    REVIEW_REPORT = "REVIEW_REPORT"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"
    WITHDRAWN = "WITHDRAWN"


class DispositionDecision(str, Enum):
    UPHELD = "UPHELD"
    DISMISSED = "DISMISSED"


class PurchaseKind(str, Enum):
    TASTING = "TASTING"
    MERCHANDISE = "MERCHANDISE"
    TICKET = "TICKET"
    MEAL = "MEAL"


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class UserRole(str, Enum):
    ANONYMOUS = "Anonymous"
    MEMBER = "Member"
    HOST_OPERATOR = "HostOperator"
    PLATFORM_ADMIN = "PlatformAdmin"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------

# common_fields: true — id + created_at + updated_at + version
class HostBusiness(TypedDict):
    id: str
    legal_name: str
    category: str
    address_line1: str
    state_code: str
    arrival_window_start_hour: int
    arrival_window_end_hour: int
    self_contained_required: bool
    onboarding_status: str
    posture: str
    effective_capacity: int
    committed_sites: int
    free_sites: int
    latest_checkout_at: Optional[str]
    seasonal_windows_reserved_sites: int
    electric_site_count: int
    patronization_credit_cents: int
    host_rating_average: float
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class HostParkingSite(TypedDict):
    id: str
    host_id: str
    site_label: str
    site_class: str
    max_vehicle_length_feet: int
    has_electric: bool
    electric_service_code: str
    blocks_sites: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class Member(TypedDict):
    id: str
    email: str
    full_name: str
    plan_tier: str
    subscription_status: str
    standing_score: int
    strike_count: int
    removal_status: str
    guest_passes_remaining: int
    home_state_code: str
    total_stays_completed: int
    member_rating_average: float
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class MemberVehicle(TypedDict):
    id: str
    member_id: str
    vehicle_class: str
    length_feet: int
    self_contained: bool
    inspection_state_code: str
    inspection_expires_on: Optional[str]
    is_primary: bool
    created_at: str
    # NO updated_at, NO version


# common_fields: true
class HostAvailabilityWindow(TypedDict):
    id: str
    host_id: str
    kind: str
    label: str
    start_date: str
    end_date: str
    window_status: str
    capacity_override: int
    reserved_sites: int
    member_capacity_ceiling: int
    created_at: str
    updated_at: str
    version: int


# common_fields: true
class StayRequest(TypedDict):
    id: str
    host_id: str
    member_id: str
    vehicle_id: str
    arrival_date: str
    nights: int
    departure_date: str
    occupancy_start: str
    occupancy_end: str
    party_size: int
    electric_request_code: str
    request_depth: int
    request_status: str
    count_toward_capacity: bool
    same_day_hold: bool
    confirmed_site_id: Optional[str]
    ancillary_charge_cents: int
    cancellation_fee_cents: int
    checked_in_at: Optional[str]
    checked_out_at: Optional[str]
    no_show_recorded_at: Optional[str]
    request_origin: str
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class HostReview(TypedDict):
    id: str
    host_id: str
    author_review_id: Optional[str]
    subject_member_id: Optional[str]
    subject_host_id: Optional[str]
    author_kind: str
    author_member_id: Optional[str]
    rating: int
    public_note: str
    private_report: Optional[str]
    review_status: str
    advance_notice_hours: Optional[int]
    counter_review_count: int
    created_at: str
    # NO updated_at, NO version


# common_fields: true
class Incident(TypedDict):
    id: str
    member_id: str
    host_id: str
    severity: str
    origin: str
    incident_status: str
    narrative: str
    waived_days_remaining: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class ConductDisposition(TypedDict):
    id: str
    incident_id: str
    member_id: str
    requested_decision: Optional[str]
    decided_by_display_name: str
    decision: str
    decided_at: str
    created_at: str
    # NO updated_at, NO version


# common_fields: true
class HostPatronizationRecord(TypedDict):
    id: str
    host_id: str
    member_id: str
    stay_request_id: str
    receipt_cents: int
    purchase_kind: str
    verification_code: str
    verification_status: str
    host_credit_cents: int
    created_at: str
    updated_at: str
    version: int


# Composite read shapes (not persisted resources)
class HostCapacitySummary(TypedDict):
    capacity_basis: str
    base_capacity: int
    effective_capacity: int
    committed_sites_reserved_basis: int
    committed_sites_occupied_basis: int
    free_sites: int
    active_window_id: Optional[str]
    active_window_member_ceiling: Optional[int]
    latest_checkout_at: Optional[str]
    posture: str


class SiteAvailability(TypedDict):
    site_id: str
    occupied_intervals: List[dict]
    blocked_by_site_labels: List[str]
    is_assignable: bool


class ClockState(TypedDict):
    current_utc: str
    activated_window_ids: List[str]
    deactivated_window_ids: List[str]