"""Domain enums and response shapes for the merchandise API.

Only the statuses, roles and field sets the PRD names are modelled here.
``id`` carries no type prefix; append-only rows (price integrity audits) expose
``id`` and ``created_at`` only and carry no ``updated_at`` or ``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    """The seven business roles plus the harness-only administrator."""

    MERCHANDISE_BUYER = "MerchandiseBuyer"
    STORE_OPERATIONS_MANAGER = "StoreOperationsManager"
    IMPORT_COORDINATOR = "ImportCoordinator"
    DISTRIBUTION_CENTER_OPERATOR = "DistributionCenterOperator"
    RESET_CALENDAR_PLANNER = "ResetCalendarPlanner"
    MERCHANDISE_ANALYST = "MerchandiseAnalyst"
    LEGAL_COST_ENGINEER = "LegalCostEngineer"
    PLATFORM_ADMIN = "PlatformAdmin"


class PricePointStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"


class SeasonWindowStatus(str, Enum):
    DRAFT = "DRAFT"
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ExclusivePackProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class ItemStatus(str, Enum):
    DENOMINATED = "DENOMINATED"
    PRICE_ASSIGNED = "PRICE_ASSIGNED"
    COST_PENDING = "COST_PENDING"
    DELETE_REVIEW = "DELETE_REVIEW"
    ACTIVE = "ACTIVE"
    DELETED = "DELETED"


class ContainerStatus(str, Enum):
    BOOKED = "BOOKED"
    IN_TRANSIT = "IN_TRANSIT"
    AT_PORT = "AT_PORT"
    CUSTOMS_HOLD = "CUSTOMS_HOLD"
    RECEIVED = "RECEIVED"
    ALLOCATED = "ALLOCATED"


class StoreStatus(str, Enum):
    SINGLE_PRICE = "SINGLE_PRICE"
    CONVERTING = "CONVERTING"
    MULTI_PRICE = "MULTI_PRICE"
    REVERTING = "REVERTING"


class ConversionProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ROLLBACK = "ROLLBACK"


class AisleResetStatus(str, Enum):
    PLANNED = "PLANNED"
    EXECUTING = "EXECUTING"
    EXECUTED = "EXECUTED"
    ABANDONED = "ABANDONED"


class PriceIntegrityAuditStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class AllocationLineStatus(str, Enum):
    ALLOCATED = "ALLOCATED"
    OVERFLOW = "OVERFLOW"
    RELEASED = "RELEASED"
    SHORTED = "SHORTED"
    REVERSED = "REVERSED"


class LandedCostMethod(str, Enum):
    FREIGHT_PASS_THROUGH = "FREIGHT_PASS_THROUGH"
    VENDOR_PRICE_CHANGE = "VENDOR_PRICE_CHANGE"


class BreakEvenRegime(str, Enum):
    PRICE_PENDING = "PRICE_PENDING"
    CONVERGENCE = "CONVERGENCE"
    DIVERGENCE_OR_ZERO_MARGIN = "DIVERGENCE_OR_ZERO_MARGIN"


class ConversionArtifact(str, Enum):
    """The three artefacts a conversion filings call may name."""

    SIGN_ORDER = "sign_order"
    SHELF_TAG = "shelf_tag"
    REGISTER_FILE = "register_file"


# ─── Entity shapes (every primary resource carries the common field set) ───────


class PricePoint(TypedDict, total=False):
    id: str
    label: str
    shelf_price_cents: int
    target_landed_cost_ratio: float
    issued_store_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SeasonWindow(TypedDict, total=False):
    id: str
    season_code: str
    opens_on: str
    closes_on: str
    overlapping_reset_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExclusivePackProgram(TypedDict, total=False):
    id: str
    vendor_id: str
    price_point_id: str
    pack_qty: int
    case_pack_qty: int
    formulation_code: str
    quoted_landed_cost_cents: int
    target_landed_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict, total=False):
    id: str
    sku: str
    description: str
    unit_retail_cents: int
    price_point_id: Optional[str]
    commodity_class: str
    season_code: str
    sqft_per_unit: float
    shelf_package_capacity: float
    units_per_case: int
    base_landed_cost_cents: int
    fixed_store_handling_cents: int
    variable_store_cost_cents: int
    sourcing_vendor_id: str
    on_hand_units: int
    broken_case_allowance: bool
    is_shelf_overflow: bool
    landed_cost_cents: int
    break_even_units: int
    net_contribution_cents_per_unit: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Vendor(TypedDict, total=False):
    id: str
    vendor_name: str
    country_of_origin: str
    import_flag: bool
    exclusivity_program_count: int
    created_at: str
    updated_at: str
    version: int


class Container(TypedDict, total=False):
    id: str
    vendor_id: str
    container_number: str
    port_code: str
    dc_code: str
    total_freight_cents: int
    customs_cleared: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict, total=False):
    id: str
    store_number: str
    shelf_facing_capacity_sqft: float
    conversion_price_point_id: Optional[str]
    sign_order_filed: bool
    shelf_tag_filed: bool
    register_file_locked: bool
    price_integrity_audit_count: int
    open_violation_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AisleReset(TypedDict, total=False):
    id: str
    store_id: str
    price_point_id: str
    season_window_id: str
    aisle_code: str
    starts_at: str
    ends_at: str
    allocated_shelf_sqft: float
    seasonal_changeover: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ConversionProject(TypedDict, total=False):
    id: str
    store_id: str
    from_price_point_id: str
    to_price_point_id: str
    expected_store_version: int
    coverage_delta_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PriceIntegrityAudit(TypedDict, total=False):
    """Append-only event row: id and created_at only, no updated_at, no version."""

    id: str
    store_id: str
    price_point_id: str
    audited_at: str
    observed_item_count: int
    mismatched_item_count: int
    result: str
    mismatch_ratio: float
    status: str
    created_at: str


class LandedCostHistory(TypedDict, total=False):
    id: str
    item_id: str
    container_id: Optional[str]
    method: str
    applied_amount_cents: int
    effective_sequence: int
    created_at: str


class AllocationLine(TypedDict, total=False):
    id: str
    container_id: str
    store_id: str
    item_id: str
    sequence: int
    requested_units: int
    allocated_units: int
    overflow_units: int
    released_units: int
    remaining_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BreakEvenProjection(TypedDict, total=False):
    item_id: str
    break_even_units: int
    unit_retail_cents: int
    landed_cost_cents: int
    variable_store_cost_cents: int
    net_contribution_cents_per_unit: int
    regime: str


class CoverageProjection(TypedDict, total=False):
    conversion_project_id: str
    completed_aisle_count: int
    projected_convertible_aisle_count: int
    adjusted_baseline: int
    coverage_delta_pct: float
    shortfall: bool


class MultiPriceIssueResult(TypedDict, total=False):
    store_id: str
    issued_item_count: int
    to_price_point_id: str
    rejected_item_ids: List[str]


class ClockResult(TypedDict, total=False):
    current_utc: str
    recomputed_item_count: int
    recomputed_season_window_count: int