"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    REGIONAL_MANAGER = "RegionalManager"
    STAND_OPERATOR = "StandOperator"
    SHIFT_LEAD = "ShiftLead"
    CREW_MEMBER = "CrewMember"
    LOYALTY_CUSTOMER = "LoyaltyCustomer"


class StandStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    OPEN = "OPEN"
    THROTTLED = "THROTTLED"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AgreementStatus(str, Enum):
    NOMINATED = "NOMINATED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class RecipeChannel(str, Enum):
    CORE = "CORE"
    SEASONAL = "SEASONAL"
    SECRET = "SECRET"


class RecipeTemperature(str, Enum):
    HOT = "HOT"
    ICED = "ICED"
    BLENDED = "BLENDED"


class RecipeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class DistributionStatus(str, Enum):
    STAGED = "STAGED"
    ACTIVATED = "ACTIVATED"
    SUSPENDED = "SUSPENDED"
    WITHDRAWN = "WITHDRAWN"


class LoyaltyTier(str, Enum):
    NONE = "NONE"
    SILVER = "SILVER"
    GOLD = "GOLD"


class ShiftStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    IN_PROGRESS = "IN_PROGRESS"
    RECONCILED = "RECONCILED"
    LOCKED = "LOCKED"


class AssignmentStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    CHECKED_IN = "CHECKED_IN"
    NO_SHOW = "NO_SHOW"
    CANCELLED = "CANCELLED"


class AssignmentRole(str, Enum):
    TAKER = "TAKER"
    BAR = "BAR"
    RUNNER = "RUNNER"
    LEAD = "LEAD"


class OrderSource(str, Enum):
    WINDOW = "WINDOW"
    LOYALTY_APP = "LOYALTY_APP"


class OrderQueueStatus(str, Enum):
    QUEUED = "QUEUED"
    MERGED = "MERGED"
    AT_WINDOW = "AT_WINDOW"
    SERVED = "SERVED"
    ABANDONED = "ABANDONED"


class OrderPaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"
    VOIDED = "VOIDED"


class OrderBuildStatus(str, Enum):
    QUEUED = "QUEUED"
    BUILDING = "BUILDING"
    READY = "READY"
    HANDED_OFF = "HANDED_OFF"


class OrderItemBuildStatus(str, Enum):
    PENDING = "PENDING"
    BUILDING = "BUILDING"
    READY = "READY"
    CANCELLED = "CANCELLED"


class PaymentStatus(str, Enum):
    AUTHORIZED = "AUTHORIZED"
    CAPTURED = "CAPTURED"
    REFUND_PENDING = "REFUND_PENDING"
    REFUNDED = "REFUNDED"
    VOIDED = "VOIDED"


class WindowStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_PASS = "CLOSED_PASS"
    CLOSED_BREACH = "CLOSED_BREACH"


# All entities in this domain carry the full common-field set:
# id, created_at, updated_at, version (PRD §2.4).

class Region(TypedDict, total=False):
    id: str
    name: str
    code: str
    created_at: str
    updated_at: str
    version: int


class Stand(TypedDict, total=False):
    id: str
    region_id: str
    name: str
    min_ingress_gap_seconds: int
    lane_configs: List[Dict[str, Any]]
    status: str
    consecutive_breach_windows: int
    lane_occupancy: Dict[str, int]
    created_at: str
    updated_at: str
    version: int


class CrewMember(TypedDict, total=False):
    id: str
    full_name: str
    home_stand_id: str
    hired_on: str
    food_handler_cert_expires_on: str
    created_at: str
    updated_at: str
    version: int


class OperatorAgreement(TypedDict, total=False):
    id: str
    stand_id: str
    crew_member_id: str
    revenue_share_pct: float
    nominated_by: str
    approved_by: str
    activated_on: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Recipe(TypedDict, total=False):
    id: str
    name: str
    channel: str
    base_price_cents: int
    base_build_seconds: int
    temperature_class: str
    season_start: Optional[str]
    season_end: Optional[str]
    modifiers: List[Dict[str, Any]]
    status: str
    created_at: str
    updated_at: str
    version: int


class RecipeDistribution(TypedDict, total=False):
    id: str
    recipe_id: str
    stand_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class LoyaltyAccount(TypedDict, total=False):
    id: str
    full_name: str
    home_stand_id: str
    points: int
    tier: str
    lifetime_captured_cents: int
    created_at: str
    updated_at: str
    version: int


class Shift(TypedDict, total=False):
    id: str
    stand_id: str
    starts_at: str
    ends_at: str
    is_peak: bool
    status: str
    provisional_deficit_score: Optional[int]
    reconciled_deficit_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


class ShiftAssignment(TypedDict, total=False):
    id: str
    shift_id: str
    crew_member_id: str
    role: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    stand_id: str
    loyalty_account_id: Optional[str]
    source: str
    lane_code: Optional[str]
    lane_seq: Optional[int]
    queue_status: str
    payment_status: str
    build_status: str
    subtotal_cents: int
    discount_cents: int
    total_cents: int
    outstanding_build_seconds: int
    handoff_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OrderItem(TypedDict, total=False):
    id: str
    order_id: str
    recipe_id: str
    quantity: int
    modifier_names: List[str]
    unit_price_cents: int
    line_gross_cents: int
    line_discount_cents: int
    line_net_cents: int
    build_time_seconds: int
    build_status: str
    created_at: str
    updated_at: str
    version: int


class Payment(TypedDict, total=False):
    id: str
    order_id: str
    authorized_cents: int
    captured_cents: int
    refunded_cents: int
    status: str
    refund_initiated_by: Optional[str]
    refund_decided_by: Optional[str]
    captured_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ThroughputWindow(TypedDict, total=False):
    id: str
    stand_id: str
    starts_at: str
    ends_at: str
    target_cars: int
    status: str
    served_count: Optional[int]
    provisional_projected_cars: Optional[int]
    created_at: str
    updated_at: str
    version: int
