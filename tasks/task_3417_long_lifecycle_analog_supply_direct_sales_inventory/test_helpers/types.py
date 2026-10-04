"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SUPPLY_PLANNER = "SupplyPlanner"
    CHANNEL_MANAGER = "ChannelManager"
    QUALITY_ENGINEER = "QualityEngineer"
    FIELD_ENGINEER = "FieldEngineer"
    CUSTOMER = "Customer"


class PartLifecycleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    NRND = "NRND"
    EOL_ANNOUNCED = "EOL_ANNOUNCED"
    LAST_TIME_BUY = "LAST_TIME_BUY"
    DISCONTINUED = "DISCONTINUED"


class PartPosture(str, Enum):
    NORMAL = "NORMAL"
    WATCH = "WATCH"
    SHORTAGE = "SHORTAGE"


class CustomerTier(str, Enum):
    STRATEGIC = "STRATEGIC"
    KEY = "KEY"
    STANDARD = "STANDARD"
    SMALL = "SMALL"


class CustomerChannel(str, Enum):
    DIRECT_ONLINE = "DIRECT_ONLINE"
    DIRECT_FIELD = "DIRECT_FIELD"
    DISTRIBUTOR = "DISTRIBUTOR"


class PricingScheduleStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    ALLOCATED = "ALLOCATED"
    BACKORDERED = "BACKORDERED"
    SHIPPED = "SHIPPED"
    CANCELLED = "CANCELLED"


class CapacityPoolStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AllocationRunStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class EolNoticeStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    RESCINDED = "RESCINDED"
    COMPLETED = "COMPLETED"


class LifetimeBuyStatus(str, Enum):
    APPROVED = "APPROVED"
    CANCELLED = "CANCELLED"


class QualificationSegment(str, Enum):
    AUTOMOTIVE = "AUTOMOTIVE"
    INDUSTRIAL = "INDUSTRIAL"


class QualificationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    IN_REVIEW = "IN_REVIEW"
    QUALIFIED = "QUALIFIED"
    SUSPENDED = "SUSPENDED"
    REJECTED = "REJECTED"


class ReferenceDesignStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


class DesignWinStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class Part(TypedDict, total=False):
    id: str
    part_number: str
    description: str
    package_family: str
    process_technology: str
    automotive_grade: bool
    lifecycle_status: str
    demand_rate_units_per_week: int
    buffer_multiple: float
    on_hand_units: int
    reserved_units: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict, total=False):
    id: str
    name: str
    tier: str
    channel: str
    credit_limit_cents: int
    discount_pct: float
    open_exposure_cents: int
    at_risk_design_win_count: int
    created_at: str
    updated_at: str
    version: int


class PricingSchedule(TypedDict, total=False):
    id: str
    part_id: str
    effective_from: str
    tiers: list
    status: str
    published_at: str
    created_at: str
    updated_at: str
    version: int


class SalesOrder(TypedDict, total=False):
    id: str
    customer_id: str
    channel: str
    status: str
    subtotal_cents: Optional[int]
    service_fee_cents: Optional[int]
    total_cents: Optional[int]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    id: str
    order_id: str
    part_id: str
    quantity: int
    unit_price_cents: Optional[int]
    line_total_cents: Optional[int]
    awarded_units: int
    allocation_run_id: Optional[str]
    allocation_rank: Optional[int]
    allocation_priority_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CapacityPool(TypedDict, total=False):
    id: str
    site_name: str
    process_technology: str
    period_start: str
    period_end: str
    total_units: int
    allocated_units: int
    status: str
    qualified_for_automotive: bool
    created_at: str
    updated_at: str
    version: int


class AllocationRun(TypedDict, total=False):
    id: str
    period_label: str
    status: str
    shortage_part_ids: list
    awards: list
    created_at: str
    updated_at: str
    version: int


class EolNotice(TypedDict, total=False):
    id: str
    part_id: str
    notice_date: str
    last_order_date: str
    last_ship_date: str
    reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LifetimeBuy(TypedDict, total=False):
    id: str
    eol_notice_id: str
    part_id: str
    customer_id: str
    quantity: int
    unit_price_cents: int
    ltb_value_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SiteQualification(TypedDict, total=False):
    id: str
    site_name: str
    segment: str
    status: str
    qualified_at: Optional[str]
    validity_months: int
    created_at: str
    updated_at: str
    version: int


class ReferenceDesign(TypedDict, total=False):
    id: str
    title: str
    featured_part_number: str
    status: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DesignWin(TypedDict, total=False):
    id: str
    reference_design_id: str
    customer_id: str
    part_id: str
    expected_lifetime_revenue_cents: int
    annual_volume_units: int
    start_date: str
    status: str
    at_risk: bool
    recognized_ramped_cents: int
    recognized_flat_cents: int
    recognized_revenue_cents: int
    created_at: str
    updated_at: str
    version: int
