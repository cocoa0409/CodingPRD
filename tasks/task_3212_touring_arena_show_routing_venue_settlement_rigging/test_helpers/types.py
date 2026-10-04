"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class TourStatus(str, Enum):
    PLANNING = "PLANNING"
    ROUTING = "ROUTING"
    ON_ROAD = "ON_ROAD"
    WRAP = "WRAP"
    CLOSED = "CLOSED"


class VenueStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class UnionRuleSet(str, Enum):
    IATSE = "IATSE"
    TEAMSTERS = "TEAMSTERS"
    NON_UNION = "NON_UNION"


class RiggingPointStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OUT_OF_SERVICE = "OUT_OF_SERVICE"


class DateAvailStatus(str, Enum):
    OPEN = "OPEN"
    HELD = "HELD"
    BOOKED = "BOOKED"
    RELEASED = "RELEASED"


class EngagementStatus(str, Enum):
    HOLD = "HOLD"
    CONFIRMED = "CONFIRMED"
    IN_LOAD = "IN_LOAD"
    SHOW_READY = "SHOW_READY"
    IN_PERFORMANCE = "IN_PERFORMANCE"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class DealType(str, Enum):
    FLAT_RENT = "FLAT_RENT"
    PERCENTAGE = "PERCENTAGE"


class RiggingPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class LaborCallStatus(str, Enum):
    DRAFT = "DRAFT"
    POSTED = "POSTED"
    FILLED = "FILLED"
    SETTLED = "SETTLED"
    CANCELLED = "CANCELLED"


class LaborDepartment(str, Enum):
    RIGGERS = "RIGGERS"
    LOADERS = "LOADERS"
    WARDROBE = "WARDROBE"
    ANIMAL_HANDLERS = "ANIMAL_HANDLERS"
    ELECTRICS = "ELECTRICS"


class TruckMoveStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DISPATCHED = "DISPATCHED"
    ARRIVED = "ARRIVED"
    CANCELLED = "CANCELLED"


class CargoKind(str, Enum):
    VEHICLES = "VEHICLES"
    ANIMALS = "ANIMALS"
    PROPS = "PROPS"
    RIGGING = "RIGGING"
    WARDROBE = "WARDROBE"


class SettlementStatus(str, Enum):
    OPEN = "OPEN"
    RECONCILED = "RECONCILED"
    PAID = "PAID"
    DISPUTED = "DISPUTED"


class LicenseStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    WAIVED = "WAIVED"


class InspectionKind(str, Enum):
    RIGGING = "RIGGING"
    PYRO = "PYRO"
    ANIMAL = "ANIMAL"
    VEHICLE_STUNT = "VEHICLE_STUNT"
    ELECTRICAL = "ELECTRICAL"


class UserRole(str, Enum):
    TOUR_MANAGER = "TourManager"
    VENUE_BOOKER = "VenueBooker"
    PRODUCTION_ENGINEER = "ProductionEngineer"
    LABOR_STEWARD = "LaborSteward"
    BOX_OFFICE_MANAGER = "BoxOfficeManager"
    LICENSING_MANAGER = "LicensingManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PLATFORM_ADMIN = "PlatformAdmin"


class Tour(TypedDict, total=False):
    id: str
    name: str
    status: str
    home_base_city: str
    season_start_on: str
    season_end_on: str
    market_cooldown_days: int
    royalty_reserve_pct: float
    total_gross_cents: int
    total_settlement_due_cents: int
    open_engagement_count: int
    created_at: str
    updated_at: str
    version: int


class Venue(TypedDict, total=False):
    id: str
    name: str
    market_code: str
    capacity_seats: int
    load_in_dock_doors: int
    union_rule_set: str
    standard_load_in_hours: int
    default_rent_cents: int
    percentage_share_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class RiggingPoint(TypedDict, total=False):
    id: str
    venue_id: str
    label: str
    zone: str
    max_static_load_kg: int
    max_dynamic_load_kg: int
    status: str
    engineering_review_required: bool
    created_at: str
    updated_at: str
    version: int


class DateAvail(TypedDict, total=False):
    id: str
    venue_id: str
    opens_at: str
    closes_at: str
    status: str
    held_for_engagement_id: Optional[str]
    priority_rank: int
    created_at: str
    updated_at: str
    version: int


class Engagement(TypedDict, total=False):
    id: str
    tour_id: str
    venue_id: str
    date_avail_id: str
    load_in_at: str
    first_show_at: str
    load_out_at: str
    deal_type: str
    agreed_rent_cents: int
    status: str
    hold_expires_at: str
    market_overlap_flag: bool
    created_at: str
    updated_at: str
    version: int


class RiggingPlan(TypedDict, total=False):
    id: str
    engagement_id: str
    status: str
    revision_no: int
    submitted_at: Optional[str]
    approved_by_user_id: Optional[str]
    max_dynamic_point_load_kg: int
    aggregate_static_load_kg: int
    high_risk_review_required: bool
    created_at: str
    updated_at: str
    version: int


class RiggingAllocation(TypedDict, total=False):
    id: str
    rigging_plan_id: str
    rigging_point_id: str
    static_load_kg: int
    dynamic_load_kg: int
    purpose: str
    created_at: str
    updated_at: str
    version: int


class LaborCall(TypedDict, total=False):
    id: str
    engagement_id: str
    department: str
    headcount: int
    call_start_at: str
    call_end_at: str
    hourly_rate_cents: int
    status: str
    effective_hours: float
    union_minimum_hours: int
    overtime_hours: float
    estimated_cost_cents: int
    final_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class TruckMove(TypedDict, total=False):
    id: str
    engagement_id: str
    cargo_kind: str
    truck_count: int
    arrival_at: str
    status: str
    dock_doors_needed: int
    created_at: str
    updated_at: str
    version: int


class TicketScale(TypedDict, total=False):
    id: str
    engagement_id: str
    tier_label: str
    base_price_cents: int
    seats_allocated: int
    seats_sold: int
    is_family_pack: bool
    is_group_sales_only: bool
    min_group_size: int
    on_sale_at: str
    tier_rank: int
    created_at: str
    updated_at: str
    version: int


class Settlement(TypedDict, total=False):
    id: str
    engagement_id: str
    status: str
    gross_ticket_cents: int
    venue_share_cents: int
    royalty_withheld_cents: int
    labor_total_cents: int
    promoter_net_cents: int
    reconciled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LicenseAgreement(TypedDict, total=False):
    id: str
    tour_id: str
    property_code: str
    licensor_name: str
    royalty_pct: float
    minimum_guarantee_cents: int
    starts_on: str
    ends_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SafetyInspection(TypedDict, total=False):
    id: str
    engagement_id: str
    inspection_kind: str
    scheduled_at: str
    status: str
    findings: Optional[str]
    waived_reason: Optional[str]
    permit_number: Optional[str]
    created_at: str
    updated_at: str
    version: int
