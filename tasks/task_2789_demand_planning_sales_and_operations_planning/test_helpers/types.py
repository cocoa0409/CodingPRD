"""Domain types for the Demand Planning & S&OP API: status enums, role enum, entity shapes."""

from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    SOP_ADMIN = "SopAdmin"
    DEMAND_PLANNER = "DemandPlanner"
    DEMAND_REVIEW_LEAD = "DemandReviewLead"
    SUPPLY_PLANNER = "SupplyPlanner"
    EXECUTIVE_SPONSOR = "ExecutiveSponsor"
    CUSTOMER_REP = "CustomerRep"


class PlanningCycleStatus(str, Enum):
    DEMAND_REVIEW = "DEMAND_REVIEW"
    SUPPLY_REVIEW = "SUPPLY_REVIEW"
    SCENARIO_REVIEW = "SCENARIO_REVIEW"
    EXECUTIVE_REVIEW = "EXECUTIVE_REVIEW"
    PUBLISHED = "PUBLISHED"


class CyclePosture(str, Enum):
    GREEN = "GREEN"
    AT_RISK = "AT_RISK"
    FROZEN = "FROZEN"


class SupplyReviewPolicy(str, Enum):
    NET_INVENTORY_FIRST = "NET_INVENTORY_FIRST"
    GROSS_CAPACITY_FIRST = "GROSS_CAPACITY_FIRST"


class ItemLifecycleState(str, Enum):
    PRELAUNCH = "PRELAUNCH"
    RAMP = "RAMP"
    MATURE = "MATURE"
    RUNOUT = "RUNOUT"
    DISCONTINUED = "DISCONTINUED"
    CANCELLED_NPI = "CANCELLED_NPI"


class CustomerChannel(str, Enum):
    GROCERY = "GROCERY"
    CLUB = "CLUB"
    DISCOUNT = "DISCOUNT"
    ECOMMERCE = "ECOMMERCE"


class PromotionStatus(str, Enum):
    DRAFT = "DRAFT"
    APPROVED = "APPROVED"
    CANCELLED_RUNOUT = "CANCELLED_RUNOUT"


class DemandForecastStatus(str, Enum):
    BASELINE = "BASELINE"
    UNDER_CONSENSUS = "UNDER_CONSENSUS"
    CONSENSUS_LOCKED = "CONSENSUS_LOCKED"
    RUNOUT_TRUNCATED = "RUNOUT_TRUNCATED"


class ForecastMethod(str, Enum):
    HOLT_WINTERS = "HOLT_WINTERS"
    CROSTON_FLAT = "CROSTON_FLAT"
    ANALOG_PROFILE = "ANALOG_PROFILE"


class AdjustmentType(str, Enum):
    SALES_INTELLIGENCE = "SALES_INTELLIGENCE"
    PROMOTION = "PROMOTION"
    NEW_ITEM_PLAN = "NEW_ITEM_PLAN"


class ConsensusAdjustmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ENDORSED = "ENDORSED"
    COMMITTED = "COMMITTED"
    REJECTED = "REJECTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    VOIDED = "VOIDED"


class ReviewDecision(str, Enum):
    ENDORSE = "ENDORSE"
    REJECT = "REJECT"
    REQUEST_REVISION = "REQUEST_REVISION"


class SupplyPlanStatus(str, Enum):
    PLANNED = "PLANNED"
    RATIONED = "RATIONED"
    STALE = "STALE"
    COMMITTED = "COMMITTED"


class ConstraintType(str, Enum):
    MATERIAL = "MATERIAL"
    CAPACITY = "CAPACITY"
    INVENTORY_TARGET = "INVENTORY_TARGET"
    NONE = "NONE"


class AllocationStatus(str, Enum):
    ALLOCATED = "ALLOCATED"
    WITHHELD_CREDIT_HOLD = "WITHHELD_CREDIT_HOLD"
    VOIDED = "VOIDED"


class AllocationPass(str, Enum):
    PROTECTED = "PROTECTED"
    PRO_RATA = "PRO_RATA"
    NONE = "NONE"


class ScenarioStatus(str, Enum):
    DRAFT = "DRAFT"
    EVALUATED = "EVALUATED"
    SELECTED = "SELECTED"
    SUPERSEDED = "SUPERSEDED"
    EXECUTED = "EXECUTED"


class ScenarioType(str, Enum):
    CAPACITY_INVESTMENT = "CAPACITY_INVESTMENT"
    PRICE_REALIZATION = "PRICE_REALIZATION"


class BiasFlag(str, Enum):
    NONE = "NONE"
    OVER_FORECAST = "OVER_FORECAST"
    UNDER_FORECAST = "UNDER_FORECAST"


class AccuracyGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    UNGRADED = "UNGRADED"


# --------------------------------------------------------------------------
# Entity shapes. Every record below carries id / created_at / updated_at /
# version except AccuracyRecord, which carries only id and created_at.
# --------------------------------------------------------------------------


class ProductFamily(TypedDict):
    id: str
    family_code: str
    name: str
    accountable_planner_user_id: str
    units_per_hour: float
    max_monthly_hours: float
    rolling_wmape_pct: Optional[float]
    rolling_bias_pct: Optional[float]
    bias_flag: str
    accuracy_grade: str
    scored_record_count: int
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict):
    id: str
    sku: str
    family_id: str
    unit_price_cents: int
    unit_cost_cents: int
    on_hand_units: int
    material_supply_cap_units: int
    avg_monthly_demand_units: int
    npi_ramp_pct: float
    service_level_target_pct: float
    demand_cv: float
    lead_time_days: int
    safety_stock_units: int
    reorder_point_units: int
    lifecycle_state: str
    successor_item_id: Optional[str]
    runout_end_month: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Customer(TypedDict):
    id: str
    customer_code: str
    name: str
    channel: str
    priority_rank: int
    credit_hold: bool
    created_at: str
    updated_at: str
    version: int


class CapacityBlock(TypedDict):
    id: str
    family_id: str
    start_date: str
    end_date: str
    available_hours: float
    created_at: str
    updated_at: str
    version: int


class Promotion(TypedDict):
    id: str
    item_id: str
    customer_id: str
    start_month: str
    end_month: str
    lift_pct: float
    cannibalization_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanningCycle(TypedDict):
    id: str
    cycle_code: str
    horizon_start_month: str
    horizon_end_month: str
    financial_commitment_cents: int
    supply_review_policy: str
    status: str
    reopen_count: int
    plan_value_cents: int
    gross_gap_cents: int
    selected_closure_cents: int
    residual_gap_cents: int
    constrained_plan_count: int
    posture: str
    published_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DemandForecast(TypedDict):
    id: str
    cycle_id: str
    item_id: str
    customer_id: str
    month: str
    level_units: int
    trend_units_per_month: float
    seasonal_index: float
    causal_uplift_pct: float
    method: str
    baseline_units: int
    consensus_units: int
    endorsed_adjustment_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ConsensusAdjustment(TypedDict):
    id: str
    demand_forecast_id: str
    adjustment_type: str
    promotion_id: Optional[str]
    delta_units: int
    applied_delta_units: int
    rationale: str
    status: str
    revision_round: int
    proposed_by_user_id: str
    reviewed_by_user_id: Optional[str]
    review_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupplyPlan(TypedDict):
    id: str
    cycle_id: str
    item_id: str
    gross_requirement_units: int
    target_build_units: int
    available_units: int
    material_cap_units: int
    demand_side_units: int
    constrained_units: int
    shortfall_units: int
    unallocated_units: int
    constraint_type: str
    status: str
    requires_replan: bool
    created_at: str
    updated_at: str
    version: int


class Allocation(TypedDict):
    id: str
    supply_plan_id: str
    customer_id: str
    requested_units: int
    allocated_units: int
    fill_rate_pct: float
    allocation_pass: str
    allocation_status: str
    created_at: str
    updated_at: str
    version: int


class Scenario(TypedDict):
    id: str
    cycle_id: str
    name: str
    scenario_type: str
    target_item_id: Optional[str]
    added_capacity_hours: Optional[float]
    price_increase_pct: Optional[float]
    incremental_units: int
    gross_uplift_cents: int
    investment_cost_cents: int
    pre_trade_closure_cents: int
    trade_rate_pct: float
    trade_spend_cents: int
    net_gap_closure_cents: int
    status: str
    created_by_user_id: str
    selected_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccuracyRecord(TypedDict):
    """The one immutable record: it carries only id and created_at — no
    updated_at field and no version field."""

    id: str
    cycle_id: str
    item_id: str
    customer_id: str
    actual_units: int
    forecast_units_snapshot: int
    signed_error_units: int
    abs_error_units: int
    ape_pct: Optional[float]
    accountable_planner_user_id: str
    created_at: str


class CycleAccuracySummary(TypedDict):
    record_count: int
    mape_pct: Optional[float]
    wmape_pct: Optional[float]
    bias_pct: Optional[float]
    bias_flag: str
    accuracy_grade: str
    total_actual_units: int
    total_abs_error_units: int
    worst_item_id: Optional[str]
