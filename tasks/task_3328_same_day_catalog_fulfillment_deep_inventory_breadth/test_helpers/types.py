"""Domain types: entity TypedDicts, status enums and the role enum."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CATALOG_CURATOR = "CatalogCurator"
    CUSTOMER_ACCOUNT = "CustomerAccount"
    WAREHOUSE_PICKER = "WarehousePicker"
    DC_MANAGER = "DCManager"


class Region(str, Enum):
    NORTHEAST = "NORTHEAST"
    SOUTHEAST = "SOUTHEAST"
    MIDWEST = "MIDWEST"
    SOUTHWEST = "SOUTHWEST"
    WEST = "WEST"


class OperationsPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    LOCKDOWN = "LOCKDOWN"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class FulfillmentStatus(str, Enum):
    AWAITING_RELEASE = "AWAITING_RELEASE"
    ALLOCATED = "ALLOCATED"
    PICKED = "PICKED"
    SHIPPED = "SHIPPED"
    RETURNED = "RETURNED"


class LineStatus(str, Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    PICKED = "PICKED"
    SHORT = "SHORT"
    RESTOCKED = "RESTOCKED"
    RETURNED = "RETURNED"


class PickStatus(str, Enum):
    QUEUED = "QUEUED"
    PICKING = "PICKING"
    PICKED = "PICKED"
    SHORT_CLOSED = "SHORT_CLOSED"


class ShipmentStatus(str, Enum):
    STAGED = "STAGED"
    CUTOFF_CONFIRMED = "CUTOFF_CONFIRMED"
    DISPATCHED = "DISPATCHED"
    HELD = "HELD"


class ReturnStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class ClaimStatus(str, Enum):
    OPEN = "OPEN"
    RESUMED = "RESUMED"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class CurationReviewState(str, Enum):
    UNREVIEWED = "UNREVIEWED"
    APPROVED = "APPROVED"


class CatalogStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PositioningFlag(str, Enum):
    OK = "OK"
    UNDERSTOCKED = "UNDERSTOCKED"
    LONG_TAIL_DEFICIT = "LONG_TAIL_DEFICIT"


class CommittedVariant(str, Enum):
    FORWARD_LOOKING = "FORWARD_LOOKING"
    ON_HAND_ONLY = "ON_HAND_ONLY"


class ServiceLevel(str, Enum):
    GROUND = "GROUND"
    TWO_DAY = "TWO_DAY"
    OVERNIGHT = "OVERNIGHT"


# --- common_fields: true — carries id + created_at + updated_at + version --------

class DistributionCenter(TypedDict):
    id: str
    code: str
    region: str
    local_zone: str
    local_cutoff_time: str
    local_current_time: str
    utc_offset_minutes: int
    inbound_capacity_units: int
    transit_seconds: int
    cutoff_passed: bool
    cutoff_sequence_index: int
    inbound_reserved_units: int
    operations_posture: str
    created_at: str
    updated_at: str
    version: int


class Supplier(TypedDict):
    id: str
    supplier_name: str
    home_dc_id: str
    primary_attribute_name: str
    primary_attribute_value: str
    long_tail_authorized: bool
    min_stock_commitment_units: int
    commitment_breach_count: int
    performance_rating_units: int
    created_at: str
    updated_at: str
    version: int


class CustomerAccount(TypedDict):
    id: str
    account_name: str
    delivery_zone: str
    home_region: str
    open_claim_count: int
    created_at: str
    updated_at: str
    version: int


class CatalogItem(TypedDict):
    id: str
    sku: str
    description: str
    material_spec: str
    long_tail: bool
    catalog_status: str
    unit_price_cents: int
    unit_weight_kg: float
    curated_dimension_json: dict
    curation_bundle_size: int
    curation_review_state: str
    curation_last_reviewed_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InventoriedStock(TypedDict):
    id: str
    item_id: str
    dc_id: str
    account_id: str
    on_hand_units: int
    reserved_units: int
    available_units: int
    daily_demand_units: int
    inbound_daily_units: int
    positioning_flag: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CatalogOrder(TypedDict):
    id: str
    account_id: str
    order_status: str
    fulfillment_status: str
    line_count: int
    total_small_line_fee_cents: int
    order_total_cents: int
    allocated_dc_id: Optional[str]
    same_day_committed: bool
    commit_minutes_before_cutoff: int
    damage_claim_count: int
    freight_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class CatalogOrderLine(TypedDict):
    id: str
    order_id: str
    item_id: str
    quantity: int
    allocated_dc_id: Optional[str]
    allocated_units: int
    is_small_line: bool
    line_subtotal_cents: int
    allocated_small_line_fee_cents: int
    line_total_cents: int
    line_status: str
    returned_units: int
    restocked_units: int
    damaged_units: int
    return_friction_units: int
    created_at: str
    updated_at: str
    version: int


class PickTask(TypedDict):
    id: str
    order_id: str
    line_id: str
    dc_id: str
    requested_units: int
    picked_units: int
    shortage_units: int
    shortage_disposition: str
    pick_status: str
    created_at: str
    updated_at: str
    version: int


class Shipment(TypedDict):
    id: str
    order_id: str
    dc_id: str
    shipment_status: str
    cutoff_sequence_index: int
    service_level: str
    billable_weight_kg: float
    freight_rate_cents: int
    freight_surcharge_cents: int
    freight_charge_cents: int
    promised_delivery_by: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReturnAuthorization(TypedDict):
    id: str
    order_id: str
    dc_id: str
    return_status: str
    restock_units: int
    damaged_units: int
    created_at: str
    updated_at: str
    version: int


class DamageClaim(TypedDict):
    id: str
    order_id: str
    line_id: str
    claim_units: int
    damage_value_cents: int
    claim_status: str
    disposition: str
    created_at: str
    updated_at: str
    version: int


class CurationReview(TypedDict):
    id: str
    curator_id: str
    review_status: str
    bundle_level_revision: int
    approved_count: int
    revision_round_baseline: int
    created_at: str
    updated_at: str
    version: int


class SquareFootageRequest(TypedDict):
    id: str
    account_id: str
    request_status: str
    committed_length_feet: int
    committed_variant: str
    prior_committed_length_feet: int
    created_at: str
    updated_at: str
    version: int


class SquareFootageLine(TypedDict):
    id: str
    request_id: str
    cut_list_ordinal: int
    requested_feet: int
    line_status: str
    line_committed_feet: int
    created_at: str
    updated_at: str
    version: int


# --- common_fields: false — append-only, carries ONLY id + created_at ------------

class ClockTick(TypedDict):
    id: str
    current_utc: str
    dc_local_times: dict
    created_at: str


class SupplierAvailabilityReport(TypedDict):
    id: str
    supplier_id: str
    item_id: str
    reported_available_units: int
    created_at: str


class CurationReviewItem(TypedDict):
    id: str
    review_id: str
    item_id: str
    item_level_revision: int
    item_attribute_counter: int
    created_at: str


class ItemAttribute(TypedDict):
    id: str
    item_id: str
    attribute_name: str
    attribute_value: str
    unit_of_measure: str
    created_at: str


class ItemCrossReference(TypedDict):
    id: str
    item_id: str
    referenced_manufacturer: str
    referenced_part_number: str
    compatibility_note: str
    created_at: str


PICKABLE_LINE_STATUSES: List[str] = ["PENDING", "ALLOCATED", "PICKED"]
UNAVAILABLE_LINE_STATUSES: List[str] = ["SHORT", "RESTOCKED", "RETURNED"]