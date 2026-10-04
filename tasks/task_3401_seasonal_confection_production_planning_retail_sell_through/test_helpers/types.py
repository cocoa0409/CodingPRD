"""Domain types: entity TypedDicts, status enums, role enum.

Field shapes follow PRD.md Sections 2.4, 2.5 and 3. Per PRD §2.4, every one of
the twelve resource kinds carries id, created_at, updated_at and version — no
entity omits updated_at or version.
"""
from enum import Enum
from typing import Optional, TypedDict


# ===========================================================================
# Enums (string values are the exact wire spellings from PRD.md)
# ===========================================================================

class UserRole(str, Enum):
    """The six declared roles (PRD §2.1), spelled exactly as on the wire."""
    PLATFORM_ADMIN = "PlatformAdmin"
    PRODUCTION_PLANNER = "ProductionPlanner"
    RETAILER = "Retailer"
    CATEGORY_MANAGER = "CategoryManager"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    CLAIMS_ADJUSTER = "ClaimsAdjuster"


class SeasonCode(str, Enum):
    VALENTINES = "VALENTINES"
    EASTER = "EASTER"
    HALLOWEEN = "HALLOWEEN"
    CHRISTMAS = "CHRISTMAS"


class SeasonalProgramStatus(str, Enum):
    PLANNING = "PLANNING"
    OPEN_FOR_COMMITMENTS = "OPEN_FOR_COMMITMENTS"
    LOCKED = "LOCKED"
    IN_PRODUCTION = "IN_PRODUCTION"
    SHIPPING = "SHIPPING"
    ON_SHELF = "ON_SHELF"
    DISPOSITION = "DISPOSITION"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ProgramAdvanceTarget(str, Enum):
    """Legal to_state values for the program advance endpoint (PRD §3.1-§3.9)."""
    OPEN_FOR_COMMITMENTS = "OPEN_FOR_COMMITMENTS"
    LOCKED = "LOCKED"
    IN_PRODUCTION = "IN_PRODUCTION"
    SHIPPING = "SHIPPING"
    ON_SHELF = "ON_SHELF"
    DISPOSITION = "DISPOSITION"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ProductKind(str, Enum):
    SEASONAL = "SEASONAL"
    EVERYDAY = "EVERYDAY"


class ProductionRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class RetailerTier(str, Enum):
    GOLD = "GOLD"
    SILVER = "SILVER"
    BRONZE = "BRONZE"


class CommitmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    ALLOCATED = "ALLOCATED"
    SHORTED = "SHORTED"
    FULFILLING = "FULFILLING"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class ShipmentStatus(str, Enum):
    PLANNED = "PLANNED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class HeatClaimStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    MORE_INFO = "MORE_INFO"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class HeatClaimReason(str, Enum):
    MELT = "MELT"
    BLOOM = "BLOOM"
    PACKAGING_COMPROMISE = "PACKAGING_COMPROMISE"


class HeatClaimDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"
    REQUEST_MORE_INFO = "REQUEST_MORE_INFO"


class WarehousePosture(str, Enum):
    OPEN = "OPEN"
    CONGESTED = "CONGESTED"
    FULL = "FULL"


class InventoryLotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"
    DISPOSITIONED = "DISPOSITIONED"
    DEPLETED = "DEPLETED"


class DispositionChannel(str, Enum):
    MARKDOWN = "MARKDOWN"
    SECONDARY = "SECONDARY"
    DESTRUCTION = "DESTRUCTION"


class DispositionOrderStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    REJECTED = "REJECTED"


class DispositionDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class Commodity(str, Enum):
    COCOA = "COCOA"
    SUGAR = "SUGAR"


class CommodityContractStatus(str, Enum):
    OPEN = "OPEN"
    SETTLED = "SETTLED"


# ===========================================================================
# Entity TypedDicts — every entity carries the PRD §2.4 common set
# (id, created_at, updated_at, version).
# ===========================================================================

class SeasonalProgram(TypedDict, total=False):
    id: str
    season_code: str
    season_year: int
    commitment_open_on: str
    commitment_close_on: str
    production_deadline_on: str
    ship_window_open_on: str
    ship_window_close_on: str
    on_shelf_on: str
    pull_on: str
    destroy_by_on: str
    retail_price_cents: int
    forecast_units: int
    produced_units_total: int
    committed_units_total: int
    shipped_units_total: int
    disposed_units_total: int
    reopen_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    program_id: Optional[str]  # null iff kind == EVERYDAY (PRD §3.1)
    sku_code: str
    kind: str
    molded_shape: str
    brand_protected: bool
    requires_temp_control: bool
    units_per_case: int
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict, total=False):
    id: str
    program_id: Optional[str]  # null iff the product is EVERYDAY (PRD §3.2)
    product_id: str
    line_code: str
    planned_units: int
    produced_units: int
    scheduled_start_on: str
    scheduled_end_on: str
    completed_warehouse_id: Optional[str]  # null until COMPLETE
    status: str
    created_at: str
    updated_at: str
    version: int


class RetailerAccount(TypedDict, total=False):
    id: str
    name: str
    region: str
    tier: str
    max_seasonal_units: int
    everyday_baseline_weekly_units: int
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class RetailerCommitment(TypedDict, total=False):
    id: str
    program_id: str
    retailer_id: str
    product_id: str
    committed_units: int
    allocated_units: int
    reorder_units: int
    reorder_used: bool
    revision: int
    supersedes_commitment_id: Optional[str]  # null on revision 1
    ship_window_open_on: str
    ship_window_close_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict, total=False):
    id: str
    commitment_id: str
    warehouse_id: str
    units: int
    ship_on: str
    temp_controlled: bool
    temp_control_declined_by_retailer: bool
    delivered_on: Optional[str]  # null until DELIVERED
    status: str
    created_at: str
    updated_at: str
    version: int


class HeatClaim(TypedDict, total=False):
    id: str
    shipment_id: str
    claimed_units: int
    reason: str
    evidence_note: str
    auto_approve: bool
    credit_cents: Optional[int]  # null until APPROVED (PRD §3.8)
    status: str
    created_at: str
    updated_at: str
    version: int


class Warehouse(TypedDict, total=False):
    id: str
    name: str
    temp_controlled: bool
    capacity_units: int
    in_use_units: int
    quarantined_units: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict, total=False):
    id: str
    product_id: str
    warehouse_id: str
    production_run_id: str
    lot_code: str
    units_on_hand: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DispositionOrder(TypedDict, total=False):
    id: str
    program_id: str
    product_id: str
    warehouse_id: str
    units: int
    channel: str
    markdown_pct: Optional[float]  # required iff channel == MARKDOWN
    proposed_by_user_id: str
    approved_by_user_id: Optional[str]  # null until decided
    recovered_value_cents: Optional[int]  # null until EXECUTED
    status: str
    created_at: str
    updated_at: str
    version: int


class CommodityContract(TypedDict, total=False):
    id: str
    program_id: str
    commodity: str
    quantity_units: int
    contract_price_cents_per_unit: int
    hedged_quantity_units: int
    hedge_price_cents_per_unit: Optional[int]  # required iff hedged > 0
    spot_price_cents_per_unit: Optional[int]  # set at settle
    provisional_spend_cents: int
    effective_spend_cents: Optional[int]  # set at settle (FINAL variant)
    status: str
    created_at: str
    updated_at: str
    version: int


class SellThroughReport(TypedDict, total=False):
    id: str
    retailer_id: str
    program_id: str
    week_of_on: str
    seasonal_units_sold: int
    seasonal_units_on_hand: int
    everyday_units_sold: int
    cannibalization_raw: float
    cannibalization_adjusted: float
    created_at: str
    updated_at: str
    version: int


class SupplySummary(TypedDict, total=False):
    """Computed read shape (PRD §3.9 supply summary)."""
    program_id: str
    produced_units_total: int
    committed_units_total: int
    allocated_units_total: int
    shipped_units_total: int
    disposed_units_total: int
    remaining_supply_pool_units: int
