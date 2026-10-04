"""Domain types: status enums, role enum and entity TypedDicts.

Every entity in this API carries the four system-managed properties described in
the PRD: `id`, `created_at`, `updated_at` and `version`.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class DesignApprovalState(str, Enum):
    PENDING_LICENSOR_APPROVAL = "PENDING_LICENSOR_APPROVAL"
    APPROVED = "APPROVED"
    APPROVAL_REJECTED = "APPROVAL_REJECTED"


class GarmentSku(str, Enum):
    JERSEY = "JERSEY"
    TRACTOR = "TRACTOR"
    DUFFEL = "DUFFEL"
    CAP = "CAP"
    MINI = "MINI"
    PENNANT = "PENNANT"


class ProductionTriggerType(str, Enum):
    CHAMPIONSHIP_WIN = "CHAMPIONSHIP_WIN"
    MILESTONE = "MILESTONE"
    ATHLETE_TRANSACTION = "ATHLETE_TRANSACTION"
    STANDARD = "STANDARD"


class EventOutcome(str, Enum):
    WIN_FAVORED_TEAM = "WIN_FAVORED_TEAM"
    WIN_UNDERDOG_TEAM = "WIN_UNDERDOG_TEAM"
    NO_OUTCOME = "NO_OUTCOME"


class ProductionOrderStatus(str, Enum):
    PARALLEL_HOLD = "PARALLEL_HOLD"
    COMMITTED = "COMMITTED"
    PRINTING = "PRINTING"
    RETIRED_DESTROYED = "RETIRED_DESTROYED"
    RETIRED_DONATED = "RETIRED_DONATED"


class RetireReason(str, Enum):
    OUTCOME_COMMITTED = "OUTCOME_COMMITTED"
    LOSING_OUTCOME = "LOSING_OUTCOME"
    ASSORTMENT_CHANGED = "ASSORTMENT_CHANGED"
    DEMAND_COLLAPSE = "DEMAND_COLLAPSE"


class PrintType(str, Enum):
    BASE = "BASE"
    EMBROIDER = "EMBROIDER"
    HEAT_PRESS = "HEAT_PRESS"
    PENNANT = "PENNANT"


class LayerState(str, Enum):
    PENDING_PRINT = "PENDING_PRINT"
    PRINTED = "PRINTED"
    PRINT_FAILED = "PRINT_FAILED"


class FulfillmentChannel(str, Enum):
    VENUE_RETAIL = "VENUE_RETAIL"
    EVENT_POPUP = "EVENT_POPUP"
    ECOM = "ECOM"


class FulfillmentOrderStatus(str, Enum):
    PLANNED = "PLANNED"
    PICKED = "PICKED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    DISTRESSED = "DISTRESSED"
    RETURNED = "RETURNED"


class DistressReason(str, Enum):
    LOSING_OUTCOME = "LOSING_OUTCOME"
    DEMAND_COLLAPSE = "DEMAND_COLLAPSE"
    DAMAGED_ON_SITE = "DAMAGED_ON_SITE"


class DestroyMode(str, Enum):
    DESTROY = "DESTROY"
    DONATE = "DONATE"
    SHORTFALL = "SHORTFALL"


class Carrier(str, Enum):
    RUSH_AIR = "RUSH_AIR"
    GROUND = "GROUND"


class ShipmentState(str, Enum):
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"


class AccrualState(str, Enum):
    ACCRUED = "ACCRUED"
    SETTLED = "SETTLED"


class SettlementStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REVERSED = "REVERSED"


class CounterfeitReportStatus(str, Enum):
    OPEN = "OPEN"
    ENFORCED = "ENFORCED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    LICENSING_OPS = "LicensingOps"
    DESIGN_OPS = "DesignOps"
    PRODUCTION_PLANNER = "ProductionPlanner"
    PRINT_OPERATOR = "PrintOperator"
    FULFILLMENT_COORDINATOR = "FulfillmentCoordinator"
    ENFORCEMENT_AGENT = "EnforcementAgent"
    AUDIT_ONLY = "AuditOnly"


# Terminal states are locked down absolutely: no operation leaves them.
TERMINAL_FULFILLMENT_STATES = {"DELIVERED", "RETURNED", "DISTRESSED"}
TERMINAL_PRODUCTION_STATES = {"RETIRED_DESTROYED", "RETIRED_DONATED"}

# The five quantities every terminal state protects on a fulfillment order.
FULFILLMENT_QUANTITY_FIELDS = [
    "picked_qty", "shipped_qty", "returned_qty", "destroyed_qty", "donated_qty",
]


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Licensor(TypedDict):
    id: str
    name: str
    league_code: str
    royalty_rate_pct: float
    minimum_guarantee_cents: int
    accrued_royalty_cents: int
    guarantee_recovery_block_cents: int
    accrued_unsettled_cents: int
    currency: str
    created_at: str
    updated_at: str
    version: int


class Design(TypedDict):
    id: str
    licensor_id: str
    team_code: str
    player_code: Optional[str]
    garment_sku: str
    design_name: str
    approval_state: str
    approved_version: Optional[int]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductionOrder(TypedDict):
    id: str
    licensor_id: str
    design_id: str
    team_code: str
    trigger_type: str
    event_outcome: str
    status: str
    expected_demand_qty: int
    unit_cost_cents: int
    layer_ids: List[str]
    base_units_printed: int
    accessory_units_printed: int
    hold_allocation_cents: int
    committed_inventory_cents: int
    pennants_included: bool
    retired_design_version: Optional[int]
    observed_current_design_version: Optional[int]
    win_probability_pct: float
    outcome_at: Optional[str]
    capacity_commitment_units: int
    rush_delivery_points: int
    write_down_inventory_cents: int
    destroyed_units: int
    donated_units: int
    committed_at: Optional[str]
    retired_at: Optional[str]
    retire_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrintLayer(TypedDict):
    id: str
    production_order_id: str
    design_id: str
    print_type: str
    quantity: int
    printed_qty: int
    committed_qty: int
    failed_qty: int
    layer_state: str
    design_version_checked: Optional[int]
    created_at: str
    updated_at: str
    version: int


class PrintCapacity(TypedDict):
    id: str
    city_code: str
    print_type: str
    window_start: str
    window_end: str
    capacity_qty: int
    reserved_qty: int
    available_qty: int
    rush_sla_hours: int
    created_at: str
    updated_at: str
    version: int


class PrintReservation(TypedDict):
    id: str
    print_capacity_id: str
    quantity: int
    rush_flag: bool
    needed_by: str
    reserved_at: str
    reservation_state: str
    created_at: str
    updated_at: str
    version: int


class FulfillmentOrder(TypedDict):
    id: str
    production_order_id: str
    channel: str
    destination_code: str
    quantity: int
    rush_flag: bool
    status: str
    picked_qty: int
    shipped_qty: int
    returned_qty: int
    destroyed_qty: int
    donated_qty: int
    requested_wholesale_cents: int
    realized_wholesale_cents: int
    write_down_inventory_cents: int
    distress_reason: Optional[str]
    donation_recipient_code: Optional[str]
    pick_remark: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    fulfillment_order_id: str
    carrier: str
    sla_hours: int
    shipment_state: str
    committed_at: str
    delivered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoyaltyAccrual(TypedDict):
    id: str
    licensor_id: str
    production_order_id: str
    gross_wholesale_cents: int
    basis: Optional[str]
    version_seq: int
    accrual_state: str
    settled_cents: int
    accrued_cents: int
    superseded: bool
    incurred_at: str
    created_at: str
    updated_at: str
    version: int


class MinimumGuaranteeSettlement(TypedDict):
    id: str
    licensor_id: str
    status: str
    snapped_accrued_cents: int
    guarantee_shortfall_cents: int
    max_recoverable_early_cents: int
    reserved_cents: int
    licensor_version: int
    created_at: str
    updated_at: str
    version: int


class CounterfeitReport(TypedDict):
    id: str
    licensor_id: str
    venue_code: str
    online_listing_id: str
    unit_count: int
    suspect_quantity: int
    infringement_confirmed: Optional[bool]
    royalty_leakage_cents: int
    penalty_cents: int
    total_exposure_cents: int
    report_status: str
    detected_at: str
    created_at: str
    updated_at: str
    version: int