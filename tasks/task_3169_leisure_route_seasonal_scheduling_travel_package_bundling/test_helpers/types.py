"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain carry the full common set: id, created_at,
updated_at, version (PRD §2.5).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    NETWORK_PLANNER = "NetworkPlanner"
    OPS_CONTROLLER = "OpsController"
    CREW_SCHEDULER = "CrewScheduler"
    CUSTOMER_SERVICE = "CustomerService"
    FINANCE_ANALYST = "FinanceAnalyst"


class StationKind(str, Enum):
    ORIGIN_SMALL_CITY = "ORIGIN_SMALL_CITY"
    LEISURE_DESTINATION = "LEISURE_DESTINATION"


class RoutePosture(str, Enum):
    PLANNING = "PLANNING"
    SEASONAL_ACTIVE = "SEASONAL_ACTIVE"
    SEASONALLY_SUSPENDED = "SEASONALLY_SUSPENDED"
    PERMANENTLY_CLOSED = "PERMANENTLY_CLOSED"


class WindowStatus(str, Enum):
    OPEN = "OPEN"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class PublicationStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    FROZEN = "FROZEN"
    RETIRED = "RETIRED"


class AircraftStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class FlightStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"
    OPERATED = "OPERATED"


class BaseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class CrewRole(str, Enum):
    CAPTAIN = "CAPTAIN"
    FIRST_OFFICER = "FIRST_OFFICER"
    FLIGHT_ATTENDANT = "FLIGHT_ATTENDANT"


class MemberStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FURLOUGHED = "FURLOUGHED"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    RELEASED = "RELEASED"


class ComponentKind(str, Enum):
    HOTEL = "HOTEL"
    RENTAL_CAR = "RENTAL_CAR"
    ATTRACTION_TICKET = "ATTRACTION_TICKET"


class OfferStatus(str, Enum):
    OPEN = "OPEN"
    WITHDRAWN = "WITHDRAWN"


class BookingKind(str, Enum):
    AIR_ONLY = "AIR_ONLY"
    PACKAGE = "PACKAGE"


class BookingStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    STRANDED = "STRANDED"
    STRANDED_REBOOKED = "STRANDED_REBOOKED"
    CANCELLED = "CANCELLED"


class BundleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"
    SETTLED = "SETTLED"


class AncillaryKind(str, Enum):
    SEAT_ASSIGNMENT = "SEAT_ASSIGNMENT"
    CHECKED_BAG = "CHECKED_BAG"
    CARRY_ON_BAG = "CARRY_ON_BAG"
    PRIORITY_BOARDING = "PRIORITY_BOARDING"


class PurchaseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class ReasonCode(str, Enum):
    WEATHER = "WEATHER"
    MAINTENANCE = "MAINTENANCE"
    CREW_SHORTAGE = "CREW_SHORTAGE"
    LOW_DEMAND = "LOW_DEMAND"


class DisruptionStatus(str, Enum):
    DECLARED = "DECLARED"
    RECOVERED = "RECOVERED"


class SettlementStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    CLAWED_BACK = "CLAWED_BACK"


class Station(TypedDict, total=False):
    id: str
    iata_code: str
    station_kind: str
    timezone: str
    single_station_flag: bool
    created_at: str
    updated_at: str
    version: int


class Route(TypedDict, total=False):
    id: str
    origin_station_id: str
    destination_station_id: str
    route_posture: str
    base_fare_cents: int
    weekly_frequency_cap: int
    suspended_seasons_count: int
    created_at: str
    updated_at: str
    version: int


class SeasonWindow(TypedDict, total=False):
    id: str
    route_id: str
    season_label: str
    window_start_date: str
    window_end_date: str
    window_status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SchedulePublication(TypedDict, total=False):
    id: str
    route_id: str
    season_window_id: str
    operating_days_mask: List[int]
    first_operating_date: str
    last_operating_date: str
    departure_time_local: str
    block_minutes: int
    publication_status: str
    published_at: str
    created_at: str
    updated_at: str
    version: int


class Aircraft(TypedDict, total=False):
    id: str
    tail_number: str
    seat_capacity: int
    daily_utilization_cap_minutes: int
    peak_day_cap_minutes: int
    aircraft_status: str
    created_at: str
    updated_at: str
    version: int


class FlightInstance(TypedDict, total=False):
    id: str
    publication_id: str
    route_id: str
    flight_date: str
    aircraft_id: Optional[str]
    is_peak_day: bool
    seats_sold: int
    flight_status: str
    cancelled_by_disruption_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CrewBase(TypedDict, total=False):
    id: str
    base_station_id: str
    base_code: str
    base_status: str
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict, total=False):
    id: str
    crew_base_id: str
    employee_number: str
    crew_role: str
    member_status: str
    created_at: str
    updated_at: str
    version: int


class CrewAssignment(TypedDict, total=False):
    id: str
    flight_instance_id: str
    crew_member_id: str
    assignment_status: str
    created_at: str
    updated_at: str
    version: int


class SupplierOffer(TypedDict, total=False):
    id: str
    supplier_code: str
    component_kind: str
    destination_station_id: str
    net_cost_cents: int
    sell_price_cents: int
    offer_status: str
    created_at: str
    updated_at: str
    version: int


class Booking(TypedDict, total=False):
    id: str
    flight_instance_id: str
    passenger_count: int
    booking_kind: str
    base_fare_total_cents: int
    ancillary_total_cents: int
    package_bundle_id: Optional[str]
    stranded_until_date: Optional[str]
    booking_status: str
    created_at: str
    updated_at: str
    version: int


class PackageBundle(TypedDict, total=False):
    id: str
    booking_id: str
    hotel_offer_id: str
    rental_car_offer_id: Optional[str]
    attraction_offer_id: Optional[str]
    bundle_price_cents: int
    bundle_status: str
    created_at: str
    updated_at: str
    version: int


class AncillaryPurchase(TypedDict, total=False):
    id: str
    booking_id: str
    ancillary_kind: str
    amount_cents: int
    purchase_status: str
    created_at: str
    updated_at: str
    version: int


class DisruptionEvent(TypedDict, total=False):
    id: str
    route_id: str
    flight_instance_id: str
    reason_code: str
    disruption_status: str
    created_at: str
    updated_at: str
    version: int


class SupplierSettlement(TypedDict, total=False):
    id: str
    supplier_code: str
    period_start_date: str
    period_end_date: str
    gross_payable_cents: int
    clawback_cents: int
    settlement_status: str
    created_at: str
    updated_at: str
    version: int
