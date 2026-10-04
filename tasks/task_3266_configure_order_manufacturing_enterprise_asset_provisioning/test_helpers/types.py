"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class AccountTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIER = "PREMIER"
    FEDERAL = "FEDERAL"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ProgramStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    RETIRED = "RETIRED"


class ChassisCategory(str, Enum):
    LAPTOP = "LAPTOP"
    DESKTOP = "DESKTOP"
    SERVER = "SERVER"
    WORKSTATION = "WORKSTATION"


class ChassisStatus(str, Enum):
    CATALOG = "CATALOG"
    EOL = "EOL"


class ComponentKind(str, Enum):
    CPU = "CPU"
    MEMORY = "MEMORY"
    STORAGE = "STORAGE"
    GPU = "GPU"
    NIC = "NIC"
    PSU = "PSU"
    WIFI = "WIFI"
    DISPLAY = "DISPLAY"
    OS_IMAGE = "OS_IMAGE"


class ComponentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EOL = "EOL"


class RuleType(str, Enum):
    ALLOWED = "ALLOWED"
    REQUIRES = "REQUIRES"
    EXCLUDES = "EXCLUDES"
    MIN_QTY = "MIN_QTY"


class TemplateStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LOCKED = "LOCKED"
    RETIRED = "RETIRED"


class ConfigurationStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class OrderBuildStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ALLOCATED = "ALLOCATED"
    IN_PRODUCTION = "IN_PRODUCTION"
    BUILT = "BUILT"
    ON_HOLD = "ON_HOLD"
    CANCELLED = "CANCELLED"


class OrderShipStatus(str, Enum):
    PENDING = "PENDING"
    STAGED = "STAGED"
    PARTIALLY_SHIPPED = "PARTIALLY_SHIPPED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"


class OrderLineStatus(str, Enum):
    OPEN = "OPEN"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class ShipToMode(str, Enum):
    SINGLE_ADDRESS = "SINGLE_ADDRESS"
    DROP_SHIP_EMPLOYEES = "DROP_SHIP_EMPLOYEES"


class BuildJobStatus(str, Enum):
    QUEUED = "QUEUED"
    ALLOCATED = "ALLOCATED"
    BUILDING = "BUILDING"
    COMPLETE = "COMPLETE"
    SHORTAGE_BLOCKED = "SHORTAGE_BLOCKED"
    CANCELLED = "CANCELLED"


class SubstitutionStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class WaveStatus(str, Enum):
    PLANNED = "PLANNED"
    RELEASED = "RELEASED"
    SHIPPED = "SHIPPED"
    RECEIVED = "RECEIVED"
    CANCELLED = "CANCELLED"


class AssetStatus(str, Enum):
    STAGED = "STAGED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    RECOVERY_REQUESTED = "RECOVERY_REQUESTED"
    RECOVERED = "RECOVERED"


class EntitlementTier(str, Enum):
    BASIC = "BASIC"
    NBD = "NBD"
    ONSITE_4H = "ONSITE_4H"


class EntitlementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class RecoveryProgramKind(str, Enum):
    RECYCLE = "RECYCLE"
    RESALE_CREDIT = "RESALE_CREDIT"


class RecoveryStatus(str, Enum):
    INITIATED = "INITIATED"
    LABEL_ISSUED = "LABEL_ISSUED"
    RECEIVED = "RECEIVED"
    CREDITED = "CREDITED"
    RECYCLED = "RECYCLED"
    CANCELLED = "CANCELLED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ACCOUNT_MANAGER = "AccountManager"
    CUSTOMER_USER = "CustomerUser"
    FACTORY_OPS = "FactoryOps"


class CustomerAccount(TypedDict, total=False):
    id: str
    company_name: str
    account_tier: str
    credit_limit_cents: int
    outstanding_cents: int
    recovery_credit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AccountProgram(TypedDict, total=False):
    id: str
    account_id: str
    name: str
    locked: bool
    asset_tag_prefix: str
    custom_image_ref: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ChassisModel(TypedDict, total=False):
    id: str
    model_code: str
    category: str
    base_price_cents: int
    build_duration_hours: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Component(TypedDict, total=False):
    id: str
    sku: str
    kind: str
    price_cents: int
    lead_time_days: int
    stock_on_hand: int
    reserved_units: int
    available_units: int
    revision: str
    status: str
    created_at: str
    updated_at: str
    version: int


# CompatibilityRule carries ONLY id + created_at (immutable, no version/updated_at)
class CompatibilityRule(TypedDict, total=False):
    id: str
    chassis_model_id: str
    component_id: str
    rule_type: str
    other_component_id: Optional[str]
    min_qty: Optional[int]
    created_at: str


class ConfigurationTemplate(TypedDict, total=False):
    id: str
    program_id: str
    name: str
    chassis_model_id: str
    pinned_components: list
    pinned_image_ref: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Configuration(TypedDict, total=False):
    id: str
    account_id: str
    template_id: Optional[str]
    chassis_model_id: str
    component_selections: list
    compatibility_ok: bool
    lead_time_estimate_days: Optional[int]
    committed_lead_time_days: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    account_id: str
    po_number: str
    build_status: str
    ship_status: str
    promised_ship_date: Optional[str]
    total_cents: Optional[int]
    discount_cents: Optional[int]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    configuration_id: str
    qty: int
    line_total_cents: Optional[int]
    ship_to_mode: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BuildJob(TypedDict, total=False):
    id: str
    order_id: str
    order_line_id: str
    sequence_rank: Optional[int]
    qty: int
    shortage_component_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SubstitutionRequest(TypedDict, total=False):
    id: str
    build_job_id: str
    original_component_id: str
    proposed_component_id: str
    price_delta_cents: int
    round: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DeploymentWave(TypedDict, total=False):
    id: str
    order_id: str
    wave_label: str
    ship_window_start: str
    ship_window_end: str
    destinations: list
    status: str
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict, total=False):
    id: str
    order_line_id: str
    serial_number: str
    asset_tag: str
    image_applied_ref: Optional[str]
    destination_employee_ref: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SupportEntitlement(TypedDict, total=False):
    id: str
    order_line_id: str
    tier: str
    coverage_start: str
    coverage_end: str
    parts_stocking_required: bool
    reserved_part_component_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AssetRecoveryRequest(TypedDict, total=False):
    id: str
    account_id: str
    asset_id: str
    program_kind: str
    estimated_credit_cents: Optional[int]
    final_credit_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
