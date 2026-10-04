"""Domain types: entity TypedDicts, status enums, role enum."""

from enum import Enum
from typing import Optional, TypedDict


class RolloutStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class TradeAreaStatus(str, Enum):
    SCREENING = "SCREENING"
    QUALIFIED = "QUALIFIED"
    REJECTED = "REJECTED"


class StoreStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SITE_CONTROL = "SITE_CONTROL"
    UNDER_CONSTRUCTION = "UNDER_CONSTRUCTION"
    DELIVERED = "DELIVERED"
    OPEN = "OPEN"
    KILLED = "KILLED"
    EXISTING = "EXISTING"


class FormatType(str, Enum):
    TRADITIONAL = "TRADITIONAL"
    DG_FRESH = "DG_FRESH"
    DG_MARKET = "DG_MARKET"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    ACTIVE = "ACTIVE"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"
    TERMINATED = "TERMINATED"


class DCAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class RoutePlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class OpeningPlanStatus(str, Enum):
    PLANNED = "PLANNED"
    LOCKED = "LOCKED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class StudyStatus(str, Enum):
    DRAFT = "DRAFT"
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class Recommendation(str, Enum):
    PROCEED = "PROCEED"
    MITIGATE = "MITIGATE"
    BLOCKED = "BLOCKED"


class CapitalProjectKind(str, Enum):
    REMODEL = "REMODEL"
    RELOCATION = "RELOCATION"
    NEW_BUILD = "NEW_BUILD"


class CapitalProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class EventType(str, Enum):
    PROGRAM_ACTIVATED = "PROGRAM_ACTIVATED"
    PROGRAM_DEACTIVATED = "PROGRAM_DEACTIVATED"
    PROGRAM_CLOSED = "PROGRAM_CLOSED"
    TRADE_AREA_QUALIFIED = "TRADE_AREA_QUALIFIED"
    STORE_OPENED = "STORE_OPENED"


class UserRole(str, Enum):
    PROGRAM_ADMIN = "PROGRAM_ADMIN"
    REAL_ESTATE_MANAGER = "REAL_ESTATE_MANAGER"
    NETWORK_PLANNER = "NETWORK_PLANNER"
    OPERATIONS_LEAD = "OPERATIONS_LEAD"
    FINANCE_ANALYST = "FINANCE_ANALYST"


class Rollout(TypedDict):
    id: str
    name: str
    fiscal_year: int
    new_build_capital_budget_cents: int
    cannibalization_coefficient: float
    status: str
    committed_capital_cents: int
    available_capital_cents: int
    event_log_cursor: int
    created_at: str
    updated_at: str
    version: int


class TradeArea(TypedDict):
    id: str
    rollout_program_id: str
    name: str
    drive_time_minutes: int
    household_count: int
    median_household_income_cents: int
    grocery_gap_pct: float
    status: str
    trade_area_score: float
    projected_revenue_cents: int
    screening_count: int
    created_at: str
    updated_at: str
    version: int


class Store(TypedDict):
    id: str
    trade_area_id: str
    name: str
    format_type: Optional[str]
    existing_store_id: Optional[str]
    status: str
    stem_miles: float
    weekly_case_volume_base: Optional[int]
    projected_revenue_cents: Optional[int]
    volume_index: float
    build_cost_cents: Optional[int]
    opening_date: Optional[str]
    open_year_sales_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class Developer(TypedDict):
    id: str
    rollout_program_id: str
    name: str
    active_agreement_count: int
    created_at: str
    updated_at: str
    version: int


class SiteControlAgreement(TypedDict):
    id: str
    store_id: str
    developer_id: str
    committed_delivery_date: str
    base_price_cents: int
    earnest_money_cents: int
    status: str
    late_days: int
    penalty_cents: int
    created_at: str
    updated_at: str
    version: int


class DistributionCenter(TypedDict):
    id: str
    rollout_program_id: str
    name: str
    store_capacity: int
    assigned_store_count: int
    remaining_capacity: int
    created_at: str
    updated_at: str
    version: int


class DCAssignment(TypedDict):
    id: str
    store_id: str
    distribution_center_id: str
    stem_miles: float
    deliveries_per_week: int
    status: str
    stem_cost_cents_per_week: int
    created_at: str
    updated_at: str
    version: int


class RoutePlan(TypedDict):
    id: str
    store_id: str
    deliveries_per_week: int
    cases_per_truck: int
    truck_fill_pct: float
    weekly_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OpeningPlan(TypedDict):
    id: str
    store_id: str
    opening_date: str
    fixture_kit_ship_date: str
    inventory_push_date: str
    peak_season: bool
    labor_hours: int
    labor_cost_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CannibalizationStudy(TypedDict):
    id: str
    store_id: str
    overlap_entries: list
    transfer_pct: float
    recommendation: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RolloutEvent(TypedDict):
    # Append-only record: carries only id + created_at, never updated_at/version.
    id: str
    rollout_program_id: str
    sequence_number: int
    event_type: str
    store_id: Optional[str]
    payload: dict
    created_at: str


class CapitalProject(TypedDict):
    id: str
    rollout_program_id: str
    kind: str
    store_id: str
    project_cost_cents: Optional[int]
    remodel_cost_cents: Optional[int]
    projected_uplift_cents: Optional[int]
    new_build_cost_cents: int
    capital_score: Optional[float]
    status: str
    decided_at: Optional[str]
    rank: Optional[int]
    submitted_by: Optional[str]
    created_at: str
    updated_at: str
    version: int
