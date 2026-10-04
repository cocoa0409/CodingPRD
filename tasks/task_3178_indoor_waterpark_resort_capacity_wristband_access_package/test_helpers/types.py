"""Domain types for the waterpark resort capacity API.

Entity TypedDicts, enumerations for every string state field, and the role enum.
Entities that carry only ``id`` and ``created_at`` are declared without
``updated_at`` or ``version``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_OPS = "platform_ops"
    FRONT_DESK = "FrontDesk"
    AQUATICS_MANAGER = "AquaticsManager"
    GATE_ATTENDANT = "GateAttendant"
    GROUP = "Group"
    ANONYMOUS = "Anonymous"


class BookingStatus(str, Enum):
    RESERVED = "RESERVED"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"


class StayStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_HOUSE = "IN_HOUSE"
    DEPARTED = "DEPARTED"


class DayPassStatus(str, Enum):
    RESERVED = "RESERVED"
    ADMITTED = "ADMITTED"
    VOID = "VOID"
    EXPIRED = "EXPIRED"


class HolderType(str, Enum):
    RESERVATION_GUEST = "RESERVATION_GUEST"
    DAY_PASS_GUEST = "DAY_PASS_GUEST"
    GROUP_MEMBER = "GROUP_MEMBER"


class WristbandStatus(str, Enum):
    ISSUED = "ISSUED"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    REISSUED = "REISSUED"


class AccessStatus(str, Enum):
    PENDING = "PENDING"
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class AttractionStatus(str, Enum):
    OPEN = "OPEN"
    LIMITED = "LIMITED"
    CLOSED = "CLOSED"


class RequiredCertification(str, Enum):
    LIFEGUARD = "LIFEGUARD"
    NONE = "NONE"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ON_DUTY = "ON_DUTY"
    ROTATED = "ROTATED"
    COMPLETED = "COMPLETED"


class LogStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class PoolPosture(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AdmissionDirection(str, Enum):
    IN = "IN"
    OUT = "OUT"


class EventStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class GrantStatus(str, Enum):
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    DECLINED = "DECLINED"


class CabanaKind(str, Enum):
    CABANA = "CABANA"
    PARTY_ROOM = "PARTY_ROOM"


class CabanaStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    HELD = "HELD"
    BOOKED = "BOOKED"
    RELEASED = "RELEASED"


class CabanaBookingStatus(str, Enum):
    HELD = "HELD"
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    COMPLETED = "COMPLETED"


class GroupKind(str, Enum):
    BIRTHDAY = "BIRTHDAY"
    SCHOOL = "SCHOOL"
    FAMILY_REUNION = "FAMILY_REUNION"
    CORPORATE = "CORPORATE"


class GroupStatus(str, Enum):
    PENDING_DEPOSIT = "PENDING_DEPOSIT"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class TierCode(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"
    VIP = "VIP"


class ActivityBookingStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class OptInGate(str, Enum):
    ADMIT = "ADMIT"
    HOLD = "HOLD"


# ---------------------------------------------------------------------------
# TypedDicts — common_fields: true (id + created_at + updated_at + version)
# ---------------------------------------------------------------------------


class Resort(TypedDict):
    id: str
    name: str
    park_capacity_occupancy_units: int
    day_pass_cap_units: int
    day_pass_reserved_units: int
    arcade_credit_rate_cents_per_unit: int
    manager_override_used: bool
    pool_posture: str
    ops_run_index: int
    managers: List[str]
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict):
    id: str
    resort_id: str
    room_type_id: str
    booking_status: str
    stay_status: str
    guest_count: int
    arrival_date: str
    departure_date: str
    nights: int
    waterpark_included_units: int
    reserved_units: int
    package_rate_total_cents: int
    package_rate_withheld_cents: int
    credited_arcade_cents: int
    checked_in_at: Optional[str]
    checked_out_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DayPass(TypedDict):
    id: str
    resort_id: str
    service_date: str
    units_requested: int
    day_pass_status: str
    price_total_cents: int
    created_at: str
    updated_at: str
    version: int


class Wristband(TypedDict):
    id: str
    resort_id: str
    holder_type: str
    reservation_id: Optional[str]
    day_pass_id: Optional[str]
    owner_name: str
    wristband_status: str
    access_status: str
    room_charge_enabled: bool
    arcade_credit_limit_cents: int
    arcade_credit_spent_cents: int
    arcade_credit_remaining_cents: int
    access_denied_reason: Optional[str]
    valid_on_service_date: str
    superseded_by_wristband_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LifeguardShift(TypedDict):
    id: str
    resort_id: str
    attraction_id: str
    staffer_name: str
    certification_code: str
    shift_date: str
    start_minute: int
    end_minute: int
    rotation_minutes: int
    shift_status: str
    created_at: str
    updated_at: str
    version: int


class WaterQualityLog(TypedDict):
    id: str
    resort_id: str
    attraction_id: str
    sampled_at: str
    ph_reading: float
    free_chlorine_ppm: float
    turbidity_ntu: float
    log_status: str
    closure_reason: Optional[str]
    superseded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdmissionEvent(TypedDict):
    id: str
    resort_id: str
    wristband_id: str
    service_date: str
    direction: str
    event_status: str
    units_delta: int
    created_at: str
    updated_at: str
    version: int


class Cabana(TypedDict):
    id: str
    resort_id: str
    cabana_label: str
    cabana_kind: str
    capacity_units: int
    cabana_status: str
    created_at: str
    updated_at: str
    version: int


class CabanaBooking(TypedDict):
    id: str
    resort_id: str
    cabana_id: str
    group_booking_id: str
    service_date: str
    start_minute: int
    end_minute: int
    hold_expires_at: Optional[str]
    members: List[str]
    member_units: int
    cabana_booking_status: str
    created_at: str
    updated_at: str
    version: int


class GroupBooking(TypedDict):
    id: str
    resort_id: str
    group_kind: str
    group_status: str
    service_date: str
    member_count: int
    deposit_paid_cents: int
    group_reserved_units: int
    created_at: str
    updated_at: str
    version: int


class ActivityBooking(TypedDict):
    id: str
    resort_id: str
    activity_session_id: str
    group_booking_id: str
    attendees: int
    reservation_id: Optional[str]
    activity_booking_status: str
    activity_rate_total_cents: int
    activity_rate_refund_cents: int
    created_at: str
    updated_at: str
    version: int


# ---------------------------------------------------------------------------
# TypedDicts — common_fields: false (id + created_at only)
# ---------------------------------------------------------------------------


class RoomType(TypedDict):
    id: str
    resort_id: str
    code: str
    max_occupancy: int
    base_rate_cents: int
    is_cabana: bool
    created_at: str


class Attraction(TypedDict):
    id: str
    resort_id: str
    name: str
    min_occupancy_units: int
    required_certification: str
    attraction_status: str
    created_at: str


class ActivitySession(TypedDict):
    id: str
    resort_id: str
    name: str
    tier_code: str
    base_price_cents: int
    capacity_units: int
    opt_in_ratio: float
    opt_in_ratio_strict: Optional[float]
    opt_in_ratio_inclusive: float
    opt_in_gate: str
    created_at: str


class ArcadeCreditGrant(TypedDict):
    id: str
    wristband_id: str
    reservation_id: Optional[str]
    amount_cents: int
    grant_status: str
    decline_reason: Optional[str]
    created_at: str


class GroupMember(TypedDict):
    id: str
    group_booking_id: str
    member_name: str
    member_units: int
    checked_in: bool
    created_at: str