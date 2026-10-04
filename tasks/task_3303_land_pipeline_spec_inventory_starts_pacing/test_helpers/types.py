"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class OptionContractState(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    DEFAULTED = "DEFAULTED"
    EXHAUSTED = "EXHAUSTED"


class TakedownState(str, Enum):
    SCHEDULED = "SCHEDULED"
    EXECUTED = "EXECUTED"
    DEFAULTED = "DEFAULTED"


class CommunityPhase(str, Enum):
    PLANNING = "PLANNING"
    OPEN_FOR_SALES = "OPEN_FOR_SALES"
    SELLING_OUT = "SELLING_OUT"
    CLOSE_OUT = "CLOSE_OUT"
    CLOSED = "CLOSED"


class CommunityPosture(str, Enum):
    OVERHELD = "OVERHELD"
    STARVED = "STARVED"
    NORMAL = "NORMAL"


class SeriesCode(str, Enum):
    EXPRESS = "EXPRESS"
    CLASSIC = "CLASSIC"
    VENTURE = "VENTURE"
    FREEDOM = "FREEDOM"


class LotState(str, Enum):
    BANKED = "BANKED"
    CONSUMED = "CONSUMED"


class BuildStage(str, Enum):
    PERMITTED = "PERMITTED"
    FOUNDATION = "FOUNDATION"
    FRAME = "FRAME"
    DRYWALL = "DRYWALL"
    COMPLETE = "COMPLETE"
    CLOSED = "CLOSED"


class SalesStatus(str, Enum):
    UNSOLD = "UNSOLD"
    RESERVED = "RESERVED"
    SOLD = "SOLD"
    CLOSED_SALE = "CLOSED_SALE"


class SalesContractState(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"


class IncentiveType(str, Enum):
    PRICE_CUT = "PRICE_CUT"
    CLOSING_COST_CREDIT = "CLOSING_COST_CREDIT"
    RATE_BUYDOWN = "RATE_BUYDOWN"


class IncentiveStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class Trade(str, Enum):
    FRAMING = "FRAMING"
    PLUMBING = "PLUMBING"
    ELECTRICAL = "ELECTRICAL"
    HVAC = "HVAC"
    MASONRY = "MASONRY"


class PacingPlanState(str, Enum):
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class UserRole(str, Enum):
    DIVISION_PRESIDENT = "DIVISION_PRESIDENT"
    LAND_MANAGER = "LAND_MANAGER"
    COMMUNITY_MANAGER = "COMMUNITY_MANAGER"
    SALES_AGENT = "SALES_AGENT"
    TRADE_PARTNER = "TRADE_PARTNER"


# All entities in this domain carry id + created_at + updated_at + version.


class LandParcel(TypedDict, total=False):
    id: str
    name: str
    market_code: str
    acres: float
    created_at: str
    updated_at: str
    version: int


class OptionContract(TypedDict, total=False):
    id: str
    land_parcel_id: str
    option_fee_cents: int
    earnest_money_cents: int
    total_lots: int
    lot_base_price_cents: int
    state: str
    executed_at: Optional[str]
    lots_taken_down: int
    cure_fee_cents: int
    created_at: str
    updated_at: str
    version: int


class Takedown(TypedDict, total=False):
    id: str
    option_contract_id: str
    community_id: str
    lot_count: int
    window_start: str
    window_end: str
    state: str
    executed_at: Optional[str]
    escalated_lot_price_cents: Optional[int]
    credit_per_lot_cents: Optional[int]
    net_due_per_lot_cents: Optional[int]
    total_net_due_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Community(TypedDict, total=False):
    id: str
    name: str
    market_code: str
    absorption_target_per_month: float
    months_supply_target: float
    phase: str
    standing_spec_count: int
    starts_this_period: int
    lifetime_closed_sales: int
    trailing_absorption_rate: float
    forward_pace_rate: float
    months_of_supply: float
    posture: str
    max_starts_remaining: int
    starts_halted: bool
    created_at: str
    updated_at: str
    version: int


class ProductSeries(TypedDict, total=False):
    id: str
    community_id: str
    series_code: str
    min_price_cents: int
    max_price_cents: int
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict, total=False):
    id: str
    community_id: str
    source_takedown_id: str
    state: str
    created_at: str
    updated_at: str
    version: int


class Home(TypedDict, total=False):
    id: str
    community_id: str
    lot_id: str
    product_series_id: str
    base_price_cents: int
    lot_premium_cents: int
    build_stage: str
    sales_status: str
    gross_price_cents: int
    adjusted_price_cents: int
    stacked_incentive_cents: int
    net_effective_price_cents: int
    completed_at: Optional[str]
    cycle_time_days: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SalesContract(TypedDict, total=False):
    id: str
    home_id: str
    buyer_name: str
    contract_price_cents: int
    state: str
    approved_at: Optional[str]
    closed_at: Optional[str]
    renegotiation_count: int
    created_at: str
    updated_at: str
    version: int


class Incentive(TypedDict, total=False):
    id: str
    community_id: str
    type: str
    value_cents: Optional[int]
    value_pct: Optional[float]
    series_code: Optional[str]
    window_start: str
    window_end: str
    auto_activate_on_overheld: bool
    cancelled: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TradePartner(TypedDict, total=False):
    id: str
    name: str
    trade: str
    created_at: str
    updated_at: str
    version: int


class CapacityCommitment(TypedDict, total=False):
    id: str
    trade_partner_id: str
    community_id: str
    period_start: str
    period_end: str
    committed_units: int
    allocated_units: int
    remaining_units: int
    created_at: str
    updated_at: str
    version: int


class PacingPlan(TypedDict, total=False):
    id: str
    community_id: str
    period_start: str
    period_end: str
    max_starts: int
    state: str
    created_at: str
    updated_at: str
    version: int
