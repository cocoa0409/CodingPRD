"""Domain types for the guest ranch API: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Role enum (PRD §2.1)
# --------------------------------------------------------------------------

class UserRole(str, Enum):
    RANCH_MANAGER = "RanchManager"
    RESERVATIONS_AGENT = "ReservationsAgent"
    HORSE_PROGRAM_DIRECTOR = "HorseProgramDirector"
    ACTIVITY_GUIDE = "ActivityGuide"
    GUEST = "Guest"
    SAFETY_OFFICER = "SafetyOfficer"


# --------------------------------------------------------------------------
# Status enums
# --------------------------------------------------------------------------

class SeasonStatus(str, Enum):
    PLANNING = "PLANNING"
    OPEN = "OPEN"
    IN_SEASON = "IN_SEASON"
    CLOSED = "CLOSED"
    OFF_SEASON = "OFF_SEASON"


class CabinStatus(str, Enum):
    READY = "READY"
    OCCUPIED = "OCCUPIED"
    TURNOVER = "TURNOVER"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class GuestStanding(str, Enum):
    GOOD = "GOOD"
    RESTRICTED = "RESTRICTED"
    SUSPENDED = "SUSPENDED"


class WaiverStatus(str, Enum):
    NONE = "NONE"
    SIGNED = "SIGNED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class AbilityRank(str, Enum):
    UNASSESSED = "UNASSESSED"
    BEGINNER = "BEGINNER"
    NOVICE = "NOVICE"
    INTERMEDIATE = "INTERMEDIATE"
    ADVANCED = "ADVANCED"


class AssessmentStatus(str, Enum):
    PENDING = "PENDING"
    EVALUATED = "EVALUATED"
    RE_EVALUATION_REQUESTED = "RE_EVALUATION_REQUESTED"
    SUPERSEDED = "SUPERSEDED"


class BookingStatus(str, Enum):
    HELD = "HELD"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    AWAITING_DEPOSIT = "AWAITING_DEPOSIT"
    DEPOSIT_PAID = "DEPOSIT_PAID"
    PAID_IN_FULL = "PAID_IN_FULL"
    PARTIALLY_REFUNDED = "PARTIALLY_REFUNDED"
    REFUNDED = "REFUNDED"
    FORFEITED = "FORFEITED"


class MemberType(str, Enum):
    ADULT = "ADULT"
    CHILD = "CHILD"


class DietaryRestriction(str, Enum):
    NONE = "NONE"
    VEGETARIAN = "VEGETARIAN"
    GLUTEN_FREE = "GLUTEN_FREE"
    DAIRY_FREE = "DAIRY_FREE"
    NUT_ALLERGY = "NUT_ALLERGY"


class PaymentKind(str, Enum):
    DEPOSIT = "DEPOSIT"
    SETTLEMENT = "SETTLEMENT"


class HorseStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    REST = "REST"
    LAME = "LAME"
    REHAB = "REHAB"
    REVIEW_HOLD = "REVIEW_HOLD"
    RETIRED = "RETIRED"


class HealthEventType(str, Enum):
    LAMENESS = "LAMENESS"
    COLIC = "COLIC"
    REST_START = "REST_START"
    REHAB_START = "REHAB_START"
    VET_CLEARANCE = "VET_CLEARANCE"
    FARRIER = "FARRIER"
    RETIREMENT = "RETIREMENT"


class ActivityType(str, Enum):
    TRAIL_RIDE = "TRAIL_RIDE"
    ARENA_LESSON = "ARENA_LESSON"
    FLY_FISHING = "FLY_FISHING"
    HIKE = "HIKE"
    KIDS_PROGRAM = "KIDS_PROGRAM"


class TerrainGrade(str, Enum):
    MEADOW = "MEADOW"
    ROLLING = "ROLLING"
    STEEP = "STEEP"
    RIVER_CROSSING = "RIVER_CROSSING"


class SlotStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    HOLD = "HOLD"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class HoldReason(str, Enum):
    MOUNT_SHORT = "MOUNT_SHORT"
    UNDERSTAFFED = "UNDERSTAFFED"


class ReadinessPosture(str, Enum):
    FROZEN = "FROZEN"
    MOUNT_SHORT = "MOUNT_SHORT"
    UNDERSTAFFED = "UNDERSTAFFED"
    STAFFED_READY = "STAFFED_READY"


class GuideRole(str, Enum):
    LEAD = "LEAD"
    ASSISTANT = "ASSISTANT"
    WRANGLER = "WRANGLER"


class AssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"


class ReservationStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class MountStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"


class StaffRoleType(str, Enum):
    WRANGLER = "WRANGLER"
    GUIDE = "GUIDE"
    KITCHEN = "KITCHEN"
    HOUSEKEEPING = "HOUSEKEEPING"


class Certification(str, Enum):
    WILDERNESS_FIRST_AID = "WILDERNESS_FIRST_AID"
    EQUINE_HANDLER = "EQUINE_HANDLER"
    FLY_CASTING = "FLY_CASTING"
    CHILD_PROGRAM = "CHILD_PROGRAM"


class EmploymentStatus(str, Enum):
    HIRED = "HIRED"
    ACTIVE = "ACTIVE"
    COMPLETED_SEASON = "COMPLETED_SEASON"
    DEPARTED_EARLY = "DEPARTED_EARLY"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    SERIOUS = "SERIOUS"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    FILED = "FILED"
    CLEARED = "CLEARED"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"
    CLOSED = "CLOSED"


class IncidentDisposition(str, Enum):
    CLEARED = "CLEARED"
    REMEDIATION_REQUIRED = "REMEDIATION_REQUIRED"


class Weekday(str, Enum):
    MONDAY = "MONDAY"
    TUESDAY = "TUESDAY"
    WEDNESDAY = "WEDNESDAY"
    THURSDAY = "THURSDAY"
    FRIDAY = "FRIDAY"
    SATURDAY = "SATURDAY"
    SUNDAY = "SUNDAY"


# --------------------------------------------------------------------------
# Entity TypedDicts
# --------------------------------------------------------------------------

class PackageTier(TypedDict):
    code: str
    adult_nightly_rate_cents: int
    child_discount_pct: float
    included_activity_credit_cents: int


class PartyMember(TypedDict):
    guest_id: str
    member_type: str
    dietary_restrictions: List[str]


class Season(TypedDict):
    id: str
    name: str
    arrival_weekday: str
    season_start_date: str
    season_end_date: str
    min_stay_nights: int
    max_stay_nights: int
    deposit_pct: float
    buyout_premium_pct: float
    no_show_penalty_cents: int
    retention_bonus_cents: int
    dining_seat_capacity: int
    package_tiers: List[PackageTier]
    season_status: str
    gross_package_revenue_cents: int
    retention_bonus_liability_cents: int
    net_surplus_cents: int
    capital_reserve_cents: int
    capital_committed_cents: int
    bed_nights_sold: int
    in_house_guest_count: int
    created_at: str
    updated_at: str
    version: int


class Cabin(TypedDict):
    id: str
    name: str
    bed_capacity: int
    cabin_status: str
    maintenance_project_code: Optional[str]
    maintenance_capital_cost_cents: int
    last_turnover_completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Guest(TypedDict):
    id: str
    full_name: str
    birth_date: str
    weight_lb: float
    age_years: int
    guest_standing: str
    waiver_signed_on: Optional[str]
    waiver_expires_on: Optional[str]
    waiver_revoked_at: Optional[str]
    equine_statute_ack: bool
    waiver_signed_by_guardian_guest_id: Optional[str]
    waiver_status: str
    current_ability_rank: str
    effective_ability_rank: str
    created_at: str
    updated_at: str
    version: int


class RiderAssessment(TypedDict):
    id: str
    guest_id: str
    requested_ability: str
    assessed_ability: Optional[str]
    assessed_by_note: Optional[str]
    evaluated_at: Optional[str]
    assessment_status: str
    re_evaluation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    season_id: str
    cabin_id: str
    lead_guest_id: str
    package_tier_code: str
    arrival_date: str
    departure_date: str
    nights: int
    is_buyout: bool
    party_members: List[PartyMember]
    party_size: int
    adult_count: int
    child_count: int
    dietary_briefing_ack: bool
    booking_status: str
    payment_status: str
    provisional_package_total_cents: int
    deposit_required_cents: int
    deposit_paid_cents: int
    payments_applied_cents: int
    refunded_cents: int
    forfeited_cents: int
    activity_surcharge_total_cents: int
    activity_credit_applied_cents: int
    no_show_count: int
    no_show_penalty_total_cents: int
    gratuity_cents: int
    folio_adjustment_total_cents: int
    realized_nights: int
    realized_subtotal_cents: int
    final_folio_total_cents: int
    folio_balance_cents: int
    cancellation_refund_pct: float
    checked_in_at: Optional[str]
    checked_out_at: Optional[str]
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Horse(TypedDict):
    id: str
    name: str
    min_rider_ability: str
    max_rider_ability: str
    weight_limit_lb: float
    horse_status: str
    scheduled_load_hours: float
    realized_load_hours: float
    consecutive_duty_days: int
    last_duty_date: Optional[str]
    last_rest_started_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Append-only herd-health record: carries ONLY id + created_at (no updated_at, no version).
class HorseHealthEvent(TypedDict):
    id: str
    horse_id: str
    event_type: str
    observed_on: str
    note: Optional[str]
    resulting_horse_status: str
    created_at: str


class ActivitySlot(TypedDict):
    id: str
    season_id: str
    activity_type: str
    starts_at: str
    ends_at: str
    duration_hours: float
    terrain_grade: str
    min_ability_rank: str
    capacity: int
    rider_surcharge_cents: int
    mount_required: bool
    slot_status: str
    hold_reason: Optional[str]
    confirmed_rider_count: int
    minor_rider_count: int
    mount_assigned_count: int
    assigned_guide_count: int
    required_guide_count: int
    readiness_posture: str
    seats_available: int
    actual_started_at: Optional[str]
    actual_ended_at: Optional[str]
    actual_duration_hours: Optional[float]
    created_at: str
    updated_at: str
    version: int


class GuideAssignment(TypedDict):
    id: str
    slot_id: str
    staff_member_id: str
    guide_role: str
    assignment_status: str
    credited_hours: float
    created_at: str
    updated_at: str
    version: int


class ActivityReservation(TypedDict):
    id: str
    slot_id: str
    booking_id: str
    guest_id: str
    assigned_horse_id: Optional[str]
    reservation_status: str
    mount_status: str
    surcharge_cents: int
    surcharge_reversed_cents: int
    rider_ability_at_booking: Optional[str]
    mount_release_count: int
    checked_in_at: Optional[str]
    completed_at: Optional[str]
    cancelled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffMember(TypedDict):
    id: str
    season_id: str
    full_name: str
    role_type: str
    certifications: List[str]
    hired_on: str
    contract_end_date: str
    housing_unit_code: Optional[str]
    housing_bunk_number: Optional[int]
    employment_status: str
    separated_on: Optional[str]
    contract_days: int
    days_worked: int
    retention_bonus_projected_cents: int
    retention_bonus_settled_cents: int
    scheduled_guide_hours: float
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict):
    id: str
    reservation_id: str
    guest_id: str
    horse_id: Optional[str]
    reported_by_staff_member_id: Optional[str]
    severity: str
    equine_activity_statute_notice_given: bool
    narrative: str
    occurred_at: str
    incident_status: str
    disposition_note: Optional[str]
    disposed_by_user_id: Optional[str]
    closed_by_user_id: Optional[str]
    remediation_completed: bool
    created_at: str
    updated_at: str
    version: int
