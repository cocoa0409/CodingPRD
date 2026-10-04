"""Domain types for the communal teppanyaki service floor: entity TypedDicts,
status enums and the role enum. Every resource family in this API declares the
common field set, so every TypedDict carries id/created_at/updated_at/version.
"""
from enum import Enum
from typing import TypedDict, Optional


class VenueStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VENTILATION_HOLD = "VENTILATION_HOLD"


class PartyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESTRICTED = "RESTRICTED"


class LoyaltyTier(str, Enum):
    NONE = "NONE"
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class TierStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class TableStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    SEATED = "SEATED"
    TURNING = "TURNING"
    MAINTENANCE = "MAINTENANCE"


class ReservationStatus(str, Enum):
    DRAFT = "DRAFT"
    REQUESTED = "REQUESTED"
    HELD = "HELD"
    SEATED = "SEATED"
    CLOSED = "CLOSED"
    NO_SHOW = "NO_SHOW"
    ABANDONED = "ABANDONED"


class SeatingStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VACATED = "VACATED"


class ChefStatus(str, Enum):
    OFF_SHIFT = "OFF_SHIFT"
    ON_STATION = "ON_STATION"
    CLEARING = "CLEARING"


class ShowPhase(str, Enum):
    SUSHI = "SUSHI"
    GRILL = "GRILL"
    DESSERT = "DESSERT"
    CELEBRATION = "CELEBRATION"


class ShowStatus(str, Enum):
    PLANNED = "PLANNED"
    STARTED = "STARTED"
    FINISHED = "FINISHED"
    SKIPPED = "SKIPPED"


class MaintenanceKind(str, Enum):
    VENTILATION_SERVICE = "VENTILATION_SERVICE"
    GRILL_REBUILD = "GRILL_REBUILD"
    HOOD_DEEP_CLEAN = "HOOD_DEEP_CLEAN"


class MaintenanceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class SushiPrepPhase(str, Enum):
    RAW_CUT = "RAW_CUT"
    ROLLED = "ROLLED"
    PLATED = "PLATED"


class SushiTicketStatus(str, Enum):
    OPEN = "OPEN"
    VOIDED = "VOIDED"


class LedgerKind(str, Enum):
    SEAT_SURCHARGE = "SEAT_SURCHARGE"
    CELEBRATION_CHARGE = "CELEBRATION_CHARGE"
    TABLE_MINIMUM_TRUEUP = "TABLE_MINIMUM_TRUEUP"


class LedgerStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class ProteinTicketStatus(str, Enum):
    POSTED = "POSTED"
    VOIDED = "VOIDED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    FLOOR_MANAGER = "FloorManager"
    HOST = "Host"
    CHEF = "Chef"
    SUSHI_CHEF = "SushiChef"


class Venue(TypedDict, total=False):
    id: str
    venue_name: str
    city_code: str
    ventilation_zone: str
    status: str
    occupancy_freeze: bool
    hood_filter_life_index: int
    filter_service_threshold_index: int
    ops_epoch: int
    shortfall_turn_debt_minutes: int
    protein_cost_cents: float
    restaurant_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class Party(TypedDict, total=False):
    id: str
    venue_id: str
    lead_guest_name: str
    contact_phone: str
    loyalty_tier: str
    no_show_count: int
    loyalty_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TableTier(TypedDict, total=False):
    id: str
    venue_id: str
    tier_code: str
    seat_capacity: int
    over_capacity_ratio: float
    base_rate_per_guest_cents: int
    minimum_bill_cents: int
    protein_gram_standard: int
    chef_show_minutes: int
    turn_time_standard_minutes: int
    turn_time_celebration_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GrillTable(TypedDict, total=False):
    id: str
    venue_id: str
    tier_code: str
    seat_capacity: int
    status: str
    maintenance_resume_at: Optional[str]
    pending_turn: bool
    guests_seated: int
    last_seated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Reservation(TypedDict, total=False):
    id: str
    venue_id: str
    party_id: str
    tier_id: str
    party_size: int
    scheduled_time: str
    payment_mode: str
    credit_to_apply_cents: int
    celebration: str
    invite_code: Optional[str]
    status: str
    hold_count: int
    hold_until: Optional[str]
    table_id: Optional[str]
    chef_assignment_id: Optional[str]
    quote_final_cents: int
    final_bill_cents: int
    check_cents: int
    seat_surcharge_cents: int
    credit_applied_cents: int
    celebration_fee_cents: int
    last_ops_epoch: int
    current_seating_id: Optional[str]
    current_sushi_show_id: Optional[str]
    current_grill_show_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TableSeating(TypedDict, total=False):
    id: str
    venue_id: str
    table_id: str
    reservation_id: str
    guest_count: int
    seated_at: str
    expected_vacate_at: str
    actual_vacated_at: Optional[str]
    occupied_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ChefAssignment(TypedDict, total=False):
    id: str
    venue_id: str
    chef_name: str
    station_zone: str
    status: str
    sequence_index: Optional[int]
    current_table_id: Optional[str]
    completed_show_count: int
    pounds_protein_issued: float
    minutes_since_show: int
    created_at: str
    updated_at: str
    version: int


class ShowPerformance(TypedDict, total=False):
    id: str
    venue_id: str
    reservation_id: str
    chef_assignment_id: str
    table_id: str
    course_phase: str
    planned_start_at: str
    actual_start_at: Optional[str]
    duration_minutes: int
    protein_grams_served: int
    status: str
    protein_ticket_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceWindow(TypedDict, total=False):
    id: str
    venue_id: str
    table_id: Optional[str]
    maintenance_kind: str
    planned_start_at: str
    planned_end_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SushiTicket(TypedDict, total=False):
    id: str
    venue_id: str
    reservation_id: str
    item_code: str
    quantity: int
    requested_at: str
    unit_price_cents: int
    prep_phase: str
    status: str
    created_at: str
    updated_at: str
    version: int


class VenueLedgerEntry(TypedDict, total=False):
    id: str
    venue_id: str
    reservation_id: str
    entry_kind: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProteinTicket(TypedDict, total=False):
    id: str
    venue_id: str
    reservation_id: str
    show_id: str
    chef_assignment_id: str
    standard_grams: int
    issued_grams: int
    variance_grams: int
    cost_cents: float
    status: str
    created_at: str
    updated_at: str
    version: int