"""Entity shapes, enumerations and role names for the fleet planning API.

Every enumeration below is transcribed from the PRD's entity and state-machine
sections. Values are plain strings so they can be sent in request payloads and
compared directly against response fields.
"""

from typing import Any, Dict, List, Optional, TypedDict

# --------------------------------------------------------------------------
# Roles (PRD section 2.1)
# --------------------------------------------------------------------------


class Role:
    PLATFORM_ADMIN = "PlatformAdmin"
    FLEET_PLANNER = "FleetPlanner"
    FLEET_CONTROLLER = "FleetController"
    REMARKETING_MANAGER = "RemarketingManager"
    MARKET_OPERATOR = "MarketOperator"


ALL_ROLES: List[str] = [
    Role.PLATFORM_ADMIN,
    Role.FLEET_PLANNER,
    Role.FLEET_CONTROLLER,
    Role.REMARKETING_MANAGER,
    Role.MARKET_OPERATOR,
]

# --------------------------------------------------------------------------
# Reference-configuration enumerations (PRD section 3.1)
# --------------------------------------------------------------------------


class MarketStatus:
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Region:
    EAST = "EAST"
    CENTRAL = "CENTRAL"
    WEST = "WEST"


class ProgramType:
    PROGRAM = "PROGRAM"
    RISK = "RISK"


class ProgramStatus:
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ChannelCode:
    AUCTION = "AUCTION"
    RETAIL_LOT = "RETAIL_LOT"
    DEALER_DIRECT = "DEALER_DIRECT"
    PROGRAM_REPURCHASE = "PROGRAM_REPURCHASE"


class ChannelStatus:
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


# --------------------------------------------------------------------------
# Depreciation policy (PRD section 3.2)
# --------------------------------------------------------------------------


class PolicyStatus:
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


# --------------------------------------------------------------------------
# Fleet planning (PRD section 3.3)
# --------------------------------------------------------------------------


class Season:
    PEAK = "PEAK"
    SHOULDER = "SHOULDER"
    OFF_PEAK = "OFF_PEAK"


class PlanStatus:
    DRAFT = "DRAFT"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class Posture:
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class AllocationStatus:
    ORDERED = "ORDERED"
    PARTIALLY_INFLEETED = "PARTIALLY_INFLEETED"
    INFLEETED = "INFLEETED"
    CANCELLED = "CANCELLED"


# --------------------------------------------------------------------------
# Vehicle: the two independent dimensions (PRD section 2.11)
# --------------------------------------------------------------------------


class FleetStatus:
    ON_ORDER = "ON_ORDER"
    IN_FLEETING = "IN_FLEETING"
    IN_SERVICE = "IN_SERVICE"
    IN_TRANSIT = "IN_TRANSIT"
    HELD_FOR_SALE = "HELD_FOR_SALE"
    SOLD = "SOLD"
    TOTAL_LOSS = "TOTAL_LOSS"


class ConditionStatus:
    SOUND = "SOUND"
    DAMAGE_REPORTED = "DAMAGE_REPORTED"
    RECONDITIONING = "RECONDITIONING"
    RECONDITIONED = "RECONDITIONED"
    TOTALED = "TOTALED"


# --------------------------------------------------------------------------
# In-fleeting tasks (PRD section 3.4)
# --------------------------------------------------------------------------


class TaskType:
    REGISTRATION = "REGISTRATION"
    LICENSING = "LICENSING"
    PREPARATION = "PREPARATION"


class TaskStatus:
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    WAIVED = "WAIVED"


# --------------------------------------------------------------------------
# Redistribution orders (PRD section 3.6)
# --------------------------------------------------------------------------


class OrderStatus:
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    REJECTED = "REJECTED"
    AUTHORIZED = "AUTHORIZED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


# --------------------------------------------------------------------------
# Damage events (PRD section 3.7)
# --------------------------------------------------------------------------


class DamageType:
    COLLISION = "COLLISION"
    HAIL = "HAIL"
    VANDALISM = "VANDALISM"
    MECHANICAL = "MECHANICAL"


class DamageStatus:
    REPORTED = "REPORTED"
    RECOVERY_PENDING = "RECOVERY_PENDING"
    RECOVERED = "RECOVERED"
    WRITTEN_OFF = "WRITTEN_OFF"
    TOTAL_LOSS_DECLARED = "TOTAL_LOSS_DECLARED"


class RecoverySource:
    CUSTOMER = "CUSTOMER"
    THIRD_PARTY_INSURER = "THIRD_PARTY_INSURER"
    OWN_INSURANCE = "OWN_INSURANCE"


# --------------------------------------------------------------------------
# Consignments (PRD section 3.8)
# --------------------------------------------------------------------------


class ConsignmentStatus:
    DRAFT = "DRAFT"
    RECONDITION_PENDING = "RECONDITION_PENDING"
    LISTED = "LISTED"
    SOLD_PENDING_SETTLEMENT = "SOLD_PENDING_SETTLEMENT"
    SETTLED = "SETTLED"
    WITHDRAWN = "WITHDRAWN"


# --------------------------------------------------------------------------
# Ledger (PRD section 2.10)
# --------------------------------------------------------------------------


class EntryType:
    CAPITALIZATION = "CAPITALIZATION"
    PREP_COST = "PREP_COST"
    TRANSPORT_COST = "TRANSPORT_COST"
    RECONDITION_COST = "RECONDITION_COST"
    RECONDITION_REVERSAL = "RECONDITION_REVERSAL"
    CHANNEL_FEE = "CHANNEL_FEE"
    DAMAGE_RECOVERY = "DAMAGE_RECOVERY"
    SALVAGE_PROCEEDS = "SALVAGE_PROCEEDS"
    DISPOSAL_PROCEEDS = "DISPOSAL_PROCEEDS"
    DISPOSAL_GAIN_LOSS = "DISPOSAL_GAIN_LOSS"


class SourceEntityType:
    VEHICLE = "Vehicle"
    IN_FLEETING_TASK = "InFleetingTask"
    REDISTRIBUTION_ORDER = "RedistributionOrder"
    DAMAGE_EVENT = "DamageEvent"
    CONSIGNMENT = "Consignment"


# --------------------------------------------------------------------------
# Valuation variants (PRD section 3.5)
# --------------------------------------------------------------------------


class AppliedVariant:
    POLICY_SCHEDULE = "POLICY_SCHEDULE"
    PROGRAM_GUARANTEE = "PROGRAM_GUARANTEE"


class MileageBand:
    WITHIN_SOFT = "WITHIN_SOFT"
    OVER_SOFT = "OVER_SOFT"
    OVER_HARD = "OVER_HARD"


# --------------------------------------------------------------------------
# Entity row shapes. Every entity except LedgerEntry carries the common
# audit quartet id / created_at / updated_at / version; LedgerEntry carries
# only id and created_at (PRD section 2.5).
# --------------------------------------------------------------------------


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class Market(CommonFields):
    code: str
    name: str
    region: str
    transport_hub_distance_km: int
    transfer_cost_per_km_cents: int
    storage_cost_per_day_cents: int
    prep_capacity_per_day: int
    registration_lead_days: int
    status: str
    in_service_unit_count: int


class VehicleSegment(CommonFields):
    code: str
    name: str
    baseline_daily_rate_cents: int
    target_utilization_pct: float
    target_revenue_per_unit_month_cents: int
    mileage_band_soft_limit_km: int
    mileage_band_hard_limit_km: int
    recondition_cap_cents: int


class ManufacturerProgram(CommonFields):
    manufacturer_name: str
    program_year: int
    program_type: str
    repurchase_guarantee_pct: float
    min_holding_days: int
    max_holding_days: int
    max_eligible_mileage_km: int
    excess_mileage_charge_cents_per_km: int
    damage_deduction_cap_cents: int
    status: str


class RemarketingChannel(CommonFields):
    code: str
    name: str
    fee_pct: float
    fixed_fee_cents: int
    expected_days_to_sell: int
    expected_proceeds_multiplier: float
    recondition_required: bool
    status: str


class DepreciationPolicy(CommonFields):
    segment_id: str
    name: str
    monthly_depreciation_pct: float
    mileage_depreciation_cents_per_km: int
    floor_residual_pct: float
    effective_from: str
    supersedes_policy_id: Optional[str]
    status: str
    created_by_user_id: str
    activated_by_user_id: Optional[str]


class FleetPlan(CommonFields):
    market_id: str
    season: str
    plan_year: int
    planned_unit_count: int
    revenue_per_unit_target_cents: int
    utilization_target_pct: float
    status: str
    posture: str
    allocated_unit_count: int
    in_fleeted_unit_count: int


class PurchaseAllocation(CommonFields):
    plan_id: str
    program_id: str
    segment_id: str
    unit_count: int
    capitalized_cost_per_unit_cents: int
    status: str
    created_vehicle_count: int
    in_fleeted_count: int


class Vehicle(CommonFields):
    allocation_id: str
    vin: str
    segment_id: str
    program_id: str
    current_market_id: str
    capitalized_cost_cents: int
    fleet_status: str
    condition_status: str
    odometer_km: int
    rented_days_total: int
    available_days_total: int
    revenue_to_date_cents: int
    total_recondition_cents: int
    registered_at: Optional[str]
    licensed_at: Optional[str]
    prep_completed_at: Optional[str]
    first_rent_ready_at: Optional[str]
    in_service_at: Optional[str]
    held_for_sale_at: Optional[str]
    net_book_value_at_hold_cents: Optional[int]


class InFleetingTask(CommonFields):
    vehicle_id: str
    market_id: str
    task_type: str
    cost_cents: int
    bay_code: Optional[str]
    window_start: Optional[str]
    window_end: Optional[str]
    status: str
    completed_at: Optional[str]


class RedistributionOrder(CommonFields):
    vehicle_id: str
    origin_market_id: str
    destination_market_id: str
    distance_km: int
    planned_depart_at: str
    planned_receive_at: str
    estimated_transport_cost_cents: int
    actual_transport_cost_cents: Optional[int]
    status: str
    revision_count: int
    rejection_reason: Optional[str]
    proposed_by_user_id: Optional[str]
    authorized_by_user_id: Optional[str]
    depart_at: Optional[str]
    receive_at: Optional[str]


class DamageEvent(CommonFields):
    vehicle_id: str
    market_id: str
    damage_type: str
    estimate_cents: int
    net_book_value_at_report_cents: int
    total_loss_required: bool
    status: str
    recovery_source: Optional[str]
    recovered_cents: Optional[int]
    recovery_alloc_recondition_cents: Optional[int]
    recovery_alloc_depreciation_cents: Optional[int]
    recovery_alloc_income_cents: Optional[int]
    salvage_proceeds_cents: Optional[int]
    total_loss_gain_loss_cents: Optional[int]


class Consignment(CommonFields):
    vehicle_id: str
    channel_id: str
    status: str
    created_by_user_id: str
    floor_price_cents: int
    recondition_authorized_cents: Optional[int]
    recondition_actual_cents: Optional[int]
    recondition_loaded_cents: Optional[int]
    listed_at: Optional[str]
    gross_proceeds_cents: Optional[int]
    channel_fee_cents: Optional[int]
    transport_to_channel_cents: Optional[int]
    net_proceeds_cents: Optional[int]
    gain_loss_cents: Optional[int]
    settled_by_user_id: Optional[str]
    settled_at: Optional[str]


class LedgerEntry(TypedDict):
    """The only entity without updated_at and without version."""

    id: str
    created_at: str
    vehicle_id: str
    entry_type: str
    amount_cents: int
    posted_at: str
    memo: str
    source_entity_type: str
    source_entity_id: str


JsonDict = Dict[str, Any]
