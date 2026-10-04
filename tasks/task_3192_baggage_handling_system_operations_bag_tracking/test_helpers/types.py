"""Domain types: status enums, role enum and entity TypedDicts.

Every principal resource in this system carries the standard four system-managed
attributes (id, created_at, updated_at, version) — the PRD states that there are
no entities that omit them — so every TypedDict below carries all four.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Status enums
# ---------------------------------------------------------------------------

class StationPosture(str, Enum):
    OPEN = "OPEN"
    CONGESTED = "CONGESTED"
    SUSPENDED = "SUSPENDED"


class FlightStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SORT_OPEN = "SORT_OPEN"
    BOARDING = "BOARDING"
    DEPARTED = "DEPARTED"
    CANCELLED = "CANCELLED"


class MakeupAreaStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ScreeningLaneStatus(str, Enum):
    ACTIVE = "ACTIVE"
    OFFLINE = "OFFLINE"


class CustodyStatus(str, Enum):
    ACCEPTED = "ACCEPTED"
    SCREENING = "SCREENING"
    SORTED = "SORTED"
    IN_MAKEUP = "IN_MAKEUP"
    LOADED = "LOADED"
    DELIVERED = "DELIVERED"
    HELD = "HELD"
    OFFLOADED = "OFFLOADED"


class ScreeningStatus(str, Enum):
    PENDING = "PENDING"
    IN_LINE = "IN_LINE"
    CLEARED = "CLEARED"
    ALARMED = "ALARMED"
    IN_INSPECTION = "IN_INSPECTION"
    FAILED = "FAILED"


class RoutingClass(str, Enum):
    STANDARD = "STANDARD"
    MANUAL = "MANUAL"
    BULK_HOLD = "BULK_HOLD"


class ItineraryType(str, Enum):
    DOMESTIC = "DOMESTIC"
    INTERNATIONAL = "INTERNATIONAL"
    INTERLINE = "INTERLINE"


class ScanPoint(str, Enum):
    INDUCTION = "INDUCTION"
    SCREENING = "SCREENING"
    SORTATION = "SORTATION"
    MAKEUP = "MAKEUP"
    LOAD = "LOAD"
    DELIVERY = "DELIVERY"


class ScanSource(str, Enum):
    AUTOMATED = "AUTOMATED"
    MANUAL = "MANUAL"


class ScanResult(str, Enum):
    OK = "OK"
    REJECT = "REJECT"


class ScreeningEventStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    CLEARED = "CLEARED"
    ALARMED = "ALARMED"
    FAILED = "FAILED"


class ScreeningResolutionOutcome(str, Enum):
    CLEARED = "CLEARED"
    REJECTED = "REJECTED"


class InspectionStatus(str, Enum):
    QUEUED = "QUEUED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"


class InspectionResolution(str, Enum):
    CLEARED = "CLEARED"
    BAG_REJECTED = "BAG_REJECTED"


class ConnectionStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    RUSH = "RUSH"
    MISSED = "MISSED"
    REACCOMMODATED = "REACCOMMODATED"


class SpecialItemType(str, Enum):
    OVERSIZE = "OVERSIZE"
    FRAGILE = "FRAGILE"
    SPORTS_EQUIPMENT = "SPORTS_EQUIPMENT"
    MOBILITY_DEVICE = "MOBILITY_DEVICE"


class ReportType(str, Enum):
    DELAYED = "DELAYED"
    DAMAGED = "DAMAGED"
    LOST = "LOST"
    PILFERED = "PILFERED"


class ReportStatus(str, Enum):
    REPORTED = "REPORTED"
    INVESTIGATING = "INVESTIGATING"
    DELIVERY_ARRANGED = "DELIVERY_ARRANGED"
    DELIVERED = "DELIVERED"
    COMPENSATED = "COMPENSATED"
    REOPENED = "REOPENED"
    CLOSED = "CLOSED"


class ReportClaimStatus(str, Enum):
    NONE = "NONE"
    FILED = "FILED"
    APPROVED = "APPROVED"
    SETTLED = "SETTLED"
    DENIED = "DENIED"


class ClaimDecision(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class DeliveryMethod(str, Enum):
    COURIER = "COURIER"
    PASSENGER_PICKUP = "PASSENGER_PICKUP"
    FORWARD_ON_NEXT_FLIGHT = "FORWARD_ON_NEXT_FLIGHT"


class DeliveryStatus(str, Enum):
    PENDING = "PENDING"
    IN_TRANSIT = "IN_TRANSIT"
    OUT_FOR_DELIVERY = "OUT_FOR_DELIVERY"
    DELIVERED = "DELIVERED"
    COMPENSATED = "COMPENSATED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ACCEPTANCE_AGENT = "AcceptanceAgent"
    SORTATION_AGENT = "SortationAgent"
    SCREENER = "Screener"
    LOAD_AGENT = "LoadAgent"
    TRANSFER_AGENT = "TransferAgent"
    BAGGAGE_SERVICE_AGENT = "BaggageServiceAgent"
    PASSENGER = "Passenger"


# ---------------------------------------------------------------------------
# Entity TypedDicts — every principal resource carries id/created_at/updated_at/version
# ---------------------------------------------------------------------------

class Station(TypedDict, total=False):
    id: str
    code: str
    name: str
    sorter_capacity_bags: int
    posture: str
    outage_active: bool
    outage_started_utc: Optional[str]
    active_bag_count: int
    manual_queue_depth: int
    open_liability_cents: int
    settled_liability_cents: int
    ops_run_index: int
    created_at: str
    updated_at: str
    version: int


class Airline(TypedDict, total=False):
    id: str
    code: str
    name: str
    interline_agreement_active: bool
    max_excess_weight_lb: float
    excess_weight_fee_cents: int
    compensation_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class Flight(TypedDict, total=False):
    id: str
    station_id: str
    airline_id: str
    flight_number: str
    bank_code: str
    scheduled_departure_utc: str
    sortation_open_utc: str
    sortation_close_utc: str
    status: str
    makeup_ready: bool
    loaded_bag_count: int
    created_at: str
    updated_at: str
    version: int


class MakeupArea(TypedDict, total=False):
    id: str
    station_id: str
    code: str
    capacity_slots: int
    buffer_minutes: int
    occupied_slots: int
    released_slots: int
    free_slots: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ScreeningLane(TypedDict, total=False):
    id: str
    station_id: str
    lane_code: str
    status: str
    last_event_end_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Bag(TypedDict, total=False):
    id: str
    station_id: str
    flight_id: Optional[str]
    makeup_area_id: Optional[str]
    tag_number: str
    passenger_name: str
    passenger_ref: str
    itinerary_type: str
    weight_lb: float
    scale_weight_lb: Optional[float]
    weight_variance_lb: Optional[float]
    length_in: float
    width_in: float
    height_in: float
    linear_in: float
    custody_status: str
    screening_status: str
    routing_class: str
    excess_weight_fee_cents: int
    handling_charge_cents: int
    priority_score: int
    assigned_makeup_utc: Optional[str]
    loaded_utc: Optional[str]
    delivered_utc: Optional[str]
    ops_run_index_at_acceptance: int
    manual_sortation_delay_minutes: int
    screen_alarm_resolution_time_minutes: int
    anomaly_note: Optional[str]
    rush_declared: bool
    scan_trail: List[dict]
    duplicate_flag: bool
    created_at: str
    updated_at: str
    version: int


class BagScan(TypedDict, total=False):
    id: str
    bag_id: str
    scan_point: str
    scan_source: str
    scan_utc: str
    result: str
    created_at: str
    updated_at: str
    version: int


class ScreeningEvent(TypedDict, total=False):
    id: str
    bag_id: str
    lane_id: str
    start_utc: str
    end_utc: str
    alarm_code: Optional[str]
    status: str
    resolution_outcome: Optional[str]
    resolved_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ManualInspectionTask(TypedDict, total=False):
    id: str
    screening_event_id: str
    station_id: str
    queue_position: int
    status: str
    assigned_to: Optional[str]
    due_utc: str
    resolution: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Connection(TypedDict, total=False):
    id: str
    bag_id: str
    inbound_flight_id: str
    onward_flight_id: str
    required_mct_minutes: int
    connect_slack_minutes: int
    status: str
    rush_declared_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpecialItem(TypedDict, total=False):
    id: str
    bag_id: str
    item_type: str
    declared_value_cents: int
    requires_manual_screening: bool
    handling_fee_cents: int
    liability_cap_cents: int
    waived_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class MishandledReport(TypedDict, total=False):
    id: str
    bag_id: str
    station_id: str
    report_type: str
    status: str
    delivery_method: Optional[str]
    compensation_offer_cents: int
    claim_status: str
    claim_amount_cents: int
    approved_cents: int
    compensation_settled_cents: int
    final_liability_cents: int
    outage_context: bool
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    mishandled_report_id: str
    requested_amount_cents: int
    decision: str
    decided_by: Optional[str]
    decided_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Delivery(TypedDict, total=False):
    id: str
    bag_id: str
    mishandled_report_id: Optional[str]
    method: str
    address_note: Optional[str]
    scheduled_utc: Optional[str]
    status: str
    delivered_utc: Optional[str]
    courier_ref: Optional[str]
    proof_required: bool
    created_at: str
    updated_at: str
    version: int