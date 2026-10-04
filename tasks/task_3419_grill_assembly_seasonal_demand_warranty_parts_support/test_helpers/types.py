"""Domain types: entity TypedDicts, status enums, role enum.

All twelve resources carry the standard system-managed fields from PRD section 2.5
(id, created_at, updated_at, version). Nullable fields are typed Optional.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


# ---------------------------------------------------------------------------
# Role enum (PRD section 2.1)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLANNER_ADMIN = "PlannerAdmin"
    CHANNEL_REP = "ChannelRep"
    ASSEMBLER = "Assembler"
    SERVICE_AGENT = "ServiceAgent"
    APP_USER = "AppUser"


# ---------------------------------------------------------------------------
# Status / category enums
# ---------------------------------------------------------------------------
class SeasonStatus(str, Enum):
    PLANNING = "PLANNING"
    BUILD = "BUILD"
    ALLOCATION = "ALLOCATION"
    IN_SEASON = "IN_SEASON"
    CLEARANCE = "CLEARANCE"
    TRANSITIONED = "TRANSITIONED"
    CLOSED = "CLOSED"


class GrillModelStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLEARANCE_ELIGIBLE = "CLEARANCE_ELIGIBLE"
    DISCONTINUED = "DISCONTINUED"
    PARTS_ONLY = "PARTS_ONLY"
    RETIRED = "RETIRED"


class ChannelType(str, Enum):
    HOME_CENTER = "HOME_CENTER"
    SPECIALTY_DEALER = "SPECIALTY_DEALER"
    DIRECT = "DIRECT"


class ServiceTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class InventoryLotStatus(str, Enum):
    BUILDING = "BUILDING"
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"
    CLOSEOUT = "CLOSEOUT"


class AllocationStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    PARTIALLY_CONSUMED = "PARTIALLY_CONSUMED"
    CONSUMED = "CONSUMED"
    DECLINED = "DECLINED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class AllocationAction(str, Enum):
    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"
    RELEASE = "RELEASE"
    REVISE = "REVISE"


class AssemblerStatus(str, Enum):
    APPLIED = "APPLIED"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"
    DECERTIFIED = "DECERTIFIED"


class AssemblerAction(str, Enum):
    CERTIFY = "CERTIFY"
    SUSPEND = "SUSPEND"
    DECERTIFY = "DECERTIFY"


class CertificationLevel(str, Enum):
    BASIC = "BASIC"
    CERTIFIED_PRO = "CERTIFIED_PRO"
    MASTER = "MASTER"


class AssemblyJobStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class JobType(str, Enum):
    RETAIL_ASSEMBLY = "RETAIL_ASSEMBLY"
    IN_HOME = "IN_HOME"


class AssemblyJobAction(str, Enum):
    ASSIGN = "ASSIGN"
    START = "START"
    COMPLETE = "COMPLETE"
    CANCEL = "CANCEL"
    NO_SHOW = "NO_SHOW"


class SaleStatus(str, Enum):
    SOLD = "SOLD"
    REGISTERED = "REGISTERED"
    RETURNED = "RETURNED"


class SaleAction(str, Enum):
    REGISTER = "REGISTER"
    RETURN = "RETURN"


class Component(str, Enum):
    BURNER = "BURNER"
    GRATE = "GRATE"
    ELECTRONICS = "ELECTRONICS"
    OTHER = "OTHER"


class AccessoryType(str, Enum):
    COVER = "COVER"
    TOOLS = "TOOLS"
    FUEL = "FUEL"
    OTHER = "OTHER"


class CoverageDetermination(str, Enum):
    IN_COVERAGE = "IN_COVERAGE"
    GOODWILL_ELIGIBLE = "GOODWILL_ELIGIBLE"
    OUT_OF_COVERAGE = "OUT_OF_COVERAGE"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    INFO_REQUESTED = "INFO_REQUESTED"
    ESCALATED = "ESCALATED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REOPENED = "REOPENED"
    SETTLED = "SETTLED"


class ClaimAction(str, Enum):
    REVIEW = "REVIEW"
    REQUEST_INFO = "REQUEST_INFO"
    SUBMIT_INFO = "SUBMIT_INFO"
    ESCALATE = "ESCALATE"
    APPROVE = "APPROVE"
    DENY = "DENY"
    REOPEN = "REOPEN"
    SETTLE = "SETTLE"


class PartSkuStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    LOW_STOCK = "LOW_STOCK"
    EXHAUSTED = "EXHAUSTED"
    SUPERSEDED = "SUPERSEDED"
    OBSOLETE = "OBSOLETE"


class PartAction(str, Enum):
    RESTOCK = "RESTOCK"
    MARK_EXHAUSTED = "MARK_EXHAUSTED"
    SUPERSEDE = "SUPERSEDE"
    MARK_OBSOLETE = "MARK_OBSOLETE"


class PartsOrderStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ALLOCATED = "ALLOCATED"
    BACKORDERED = "BACKORDERED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class PartsOrderAction(str, Enum):
    SHIP = "SHIP"
    DELIVER = "DELIVER"
    CANCEL = "CANCEL"


class FulfillmentType(str, Enum):
    WARRANTY = "WARRANTY"
    GOODWILL = "GOODWILL"
    PAID = "PAID"


class ConnectedDeviceStatus(str, Enum):
    PAIRED = "PAIRED"
    UPDATING = "UPDATING"
    UNPAIRED = "UNPAIRED"


class FirmwareAction(str, Enum):
    UPDATE = "UPDATE"
    UNPAIR = "UNPAIR"


class ModelLifecycleAction(str, Enum):
    MARK_CLEARANCE_ELIGIBLE = "MARK_CLEARANCE_ELIGIBLE"
    DISCONTINUE = "DISCONTINUE"
    MARK_PARTS_ONLY = "MARK_PARTS_ONLY"
    RETIRE = "RETIRE"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD section 2.5: every resource carries id, created_at,
# updated_at, version)
# ---------------------------------------------------------------------------
class Season(TypedDict):
    id: str
    name: str
    year: int
    build_start: str
    allocation_open: str
    in_season_start: str
    clearance_start: str
    season_end: str
    demand_forecast_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class GrillModel(TypedDict):
    id: str
    model_code: str
    model_family: str
    model_year: int
    base_price_cents: int
    demand_share_bp: int
    burner_coverage_years: int
    grate_coverage_years: int
    electronics_coverage_years: int
    other_coverage_years: int
    parts_support_years: int
    current_firmware_version: str
    status: str
    discontinued_at: Optional[str]
    support_obligation_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ChannelAccount(TypedDict):
    id: str
    name: str
    channel_type: str
    service_tier: str
    allocation_priority: int
    credit_limit_cents: int
    subsidy_bp: int
    outstanding_exposure_cents: int
    accessory_attach_rate: float
    fuel_attach_rate: float
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict):
    id: str
    season_id: str
    model_id: str
    build_week: str
    units_built: int
    units_available: int
    units_consumed: int
    recommended_build_forward_units: int
    recommended_build_actual_units: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict):
    id: str
    season_id: str
    channel_account_id: str
    model_id: str
    allocated_units: int
    committed_units: int
    status: str
    offered_at: str
    created_at: str
    updated_at: str
    version: int


class Assembler(TypedDict):
    id: str
    name: str
    certification_level: str
    service_regions: List[str]
    max_concurrent_jobs: int
    status: str
    active_job_count: int
    jobs_completed: int
    no_show_count: int
    no_show_history: List[str]
    completion_history: List[str]
    official_quality_bp: int
    provisional_quality_bp: int
    created_at: str
    updated_at: str
    version: int


class AssemblyJob(TypedDict):
    id: str
    sale_id: str
    assembler_id: Optional[str]
    job_type: str
    distance_mi: int
    window_start: Optional[str]
    window_end: Optional[str]
    fee_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AccessoryItem(TypedDict):
    sku: str
    accessory_type: str
    unit_price_cents: int


class Sale(TypedDict):
    id: str
    season_id: str
    model_id: str
    channel_account_id: str
    quantity: int
    serials: List[str]
    accessories: List[AccessoryItem]
    accessory_count: int
    has_cover: bool
    has_tools: bool
    has_fuel: bool
    unit_price_cents: int
    proof_of_purchase_token: Optional[str]
    status: str
    sold_at: str
    registered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    sale_id: str
    component: str
    failure_description: str
    serial_number: Optional[str]
    claim_date: str
    coverage_determination: str
    goodwill: bool
    provisional_settlement_cents: Optional[int]
    final_settlement_cents: Optional[int]
    settlement_delta_cents: Optional[int]
    settlement_parts_order_id: Optional[str]
    denied_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PartSku(TypedDict):
    id: str
    part_number: str
    component: str
    compatible_model_codes: List[str]
    supersession_chain_id: str
    chain_position: int
    unit_cost_cents: int
    stock_quantity: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PartsOrder(TypedDict):
    id: str
    part_id: str
    sale_id: str
    warranty_claim_id: Optional[str]
    fulfillment_type: str
    quantity: int
    resolved_part_id: str
    free_of_charge: bool
    total_cost_cents: int
    status: str
    seq_no: int
    created_at: str
    updated_at: str
    version: int


class ConnectedDevice(TypedDict):
    id: str
    sale_id: str
    app_account_id: str
    pairing_token: str
    firmware_version: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Convenience mapping used by tests that parametrize over components.
ALL_COMPONENTS: List[str] = [c.value for c in Component]

__all__ = [name for name in dir() if not name.startswith("_")]
