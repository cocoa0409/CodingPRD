"""Domain types: entity shapes, status enums, and the role enum.

Only the shape of the API surface is declared here; the behaviour lives in the PRD.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Role enum ────────────────────────────────────────

class UserRole(str, Enum):
    PASSENGER = "Passenger"
    GATE_AGENT = "GateAgent"
    OPS_CONTROLLER = "OpsController"


# ─── Status enums ─────────────────────────────────────

class StationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class StatusTier(str, Enum):
    NONE = "NONE"
    A_LIST = "A_LIST"
    A_LIST_PREFERRED = "A_LIST_PREFERRED"


class PassengerStanding(str, Enum):
    GOOD = "GOOD"
    NO_SHOW_FLAGGED = "NO_SHOW_FLAGGED"


class MaintenanceState(str, Enum):
    SERVICEABLE = "SERVICEABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class CrewRole(str, Enum):
    CAPTAIN = "CAPTAIN"
    FIRST_OFFICER = "FIRST_OFFICER"
    FLIGHT_ATTENDANT = "FLIGHT_ATTENDANT"


class CrewStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"


class LegStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELAYED = "DELAYED"
    DEPARTED = "DEPARTED"
    ARRIVED = "ARRIVED"
    CANCELLED = "CANCELLED"


class DelayCause(str, Enum):
    NONE = "NONE"
    WEATHER = "WEATHER"
    INBOUND_DELAY = "INBOUND_DELAY"
    CREW = "CREW"
    MAINTENANCE = "MAINTENANCE"


class RoutingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BROKEN = "BROKEN"


class PairingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BROKEN = "BROKEN"
    CLOSED = "CLOSED"


class BookingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class BookingChannel(str, Enum):
    DIRECT = "DIRECT"
    AGENT = "AGENT"


class JourneyStatus(str, Enum):
    BOOKED = "BOOKED"
    CHECKED_IN = "CHECKED_IN"
    BOARDED = "BOARDED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class Accommodation(str, Enum):
    NONE = "NONE"
    PREBOARD = "PREBOARD"
    FAMILY = "FAMILY"
    MIN = "MIN"


class BoardingGroup(str, Enum):
    PREBOARD = "PREBOARD"
    A = "A"
    B = "B"
    C = "C"
    FAMILY = "FAMILY"


class AssignmentSource(str, Enum):
    CHECKIN_TIME = "CHECKIN_TIME"
    UPGRADE_PURCHASE = "UPGRADE_PURCHASE"
    STATUS_PRIORITY = "STATUS_PRIORITY"
    PREBOARD_ACCOMMODATION = "PREBOARD_ACCOMMODATION"
    FAMILY_ACCOMMODATION = "FAMILY_ACCOMMODATION"
    RETIME = "RETIME"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"
    RETIMED = "RETIMED"


class ReleaseReason(str, Enum):
    NONE = "NONE"
    JOURNEY_CANCELLED = "JOURNEY_CANCELLED"
    FLIGHT_CANCELLED = "FLIGHT_CANCELLED"
    UPGRADE = "UPGRADE"
    DELAY_RETIME = "DELAY_RETIME"


class UpgradeType(str, Enum):
    EARLY_BIRD = "EARLY_BIRD"
    UPGRADED_BOARDING = "UPGRADED_BOARDING"


class UpgradeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REFUNDED = "REFUNDED"
    VOIDED = "VOIDED"


class BagStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    LOADED = "LOADED"
    DELIVERED = "DELIVERED"
    OFFLOADED = "OFFLOADED"


class CreditStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_REDEEMED = "PARTIALLY_REDEEMED"
    REDEEMED = "REDEEMED"
    EXPIRED = "EXPIRED"
    VOID = "VOID"


class RedemptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class DisruptionType(str, Enum):
    DELAY = "DELAY"
    CANCELLATION = "CANCELLATION"


class DisruptionCause(str, Enum):
    WEATHER = "WEATHER"
    INBOUND_DELAY = "INBOUND_DELAY"
    CREW = "CREW"
    MAINTENANCE = "MAINTENANCE"


# ─── Entity shapes ────────────────────────────────────

class Station(TypedDict):
    id: str
    iata_code: str
    bag_weight_limit_lbs: int
    min_connection_minutes: int
    time_zone_offset_minutes: Optional[int]
    station_status: str
    created_at: str
    updated_at: str
    version: int


class FareClass(TypedDict):
    id: str
    code: str
    included_bags: int
    change_fee_cents: int
    upgrade_discount_pct: int
    credit_validity_days: int
    preboard_eligible: bool
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class Passenger(TypedDict):
    id: str
    full_name: str
    status_tier: str
    is_min_eligible: bool
    date_of_birth: str
    standing: str
    no_show_count: int
    created_at: str
    updated_at: str
    version: int


class Aircraft(TypedDict):
    id: str
    tail_number: str
    seat_count: int
    fleet_type: str
    maintenance_state: str
    home_station_code: str
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict):
    id: str
    employee_ref: str
    crew_role: str
    qualified_fleet: str
    crew_status: str
    base_station_code: str
    created_at: str
    updated_at: str
    version: int


class FlightLeg(TypedDict):
    id: str
    flight_number: str
    origin_station_id: str
    destination_station_id: str
    scheduled_departure_utc: str
    scheduled_arrival_utc: str
    turn_target_minutes: int
    gate_agent_count: int
    ramp_agent_count: int
    capacity_seats: int
    leg_status: str
    delay_minutes: int
    delay_cause: str
    delay_propagated: bool
    boarding_start_utc: Optional[str]
    actual_departure_utc: Optional[str]
    actual_arrival_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AircraftRouting(TypedDict):
    id: str
    routing_date: str
    aircraft_id: str
    leg_ids: List[str]
    routing_status: str
    slack_minutes: int
    created_at: str
    updated_at: str
    version: int


class CrewPairing(TypedDict):
    id: str
    pairing_date: str
    crew_member_id: str
    leg_ids: List[str]
    pairing_status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict):
    id: str
    record_locator: str
    booking_status: str
    channel: str
    journey_count: int
    journey_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class PassengerJourney(TypedDict):
    id: str
    booking_id: str
    passenger_id: str
    flight_leg_id: str
    fare_class_id: str
    base_fare_cents: int
    journey_status: str
    accommodation: str
    family_anchor_journey_id: Optional[str]
    checked_in_at: Optional[str]
    no_show_penalty_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class BoardingAssignment(TypedDict):
    id: str
    journey_id: str
    flight_leg_id: str
    boarding_group: str
    boarding_position: int
    assignment_source: str
    assignment_status: str
    release_reason: str
    created_at: str
    updated_at: str
    version: int


class BoardingUpgrade(TypedDict):
    id: str
    journey_id: str
    upgrade_type: str
    price_cents: int
    position_granted: Optional[int]
    upgrade_status: str
    created_at: str
    updated_at: str
    version: int


class Bag(TypedDict):
    id: str
    journey_id: str
    weight_lbs: int
    bag_status: str
    bag_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class TravelCredit(TypedDict):
    id: str
    passenger_id: str
    source_journey_id: str
    initial_amount_cents: int
    remaining_amount_cents: int
    expires_on: str
    credit_status: str
    created_at: str
    updated_at: str
    version: int


class CreditRedemption(TypedDict):
    id: str
    credit_id: str
    journey_id: str
    amount_cents: int
    redemption_status: str
    created_at: str
    updated_at: str
    version: int


class DisruptionEvent(TypedDict):
    id: str
    flight_leg_id: str
    disruption_type: str
    cause: str
    delay_minutes: Optional[int]
    posted_utc: str
    propagation_depth: int
    created_at: str
    updated_at: str
    version: int
