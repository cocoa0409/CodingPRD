"""Domain types: entity TypedDicts, status enums, role enum.

All shapes mirror the PRD resource narratives (PRD §2.5, §3). Every one of the
thirteen resources carries the four system-managed fields ``id``,
``created_at``, ``updated_at`` and ``version`` (PRD §2.5: "All thirteen entity
types carry all four fields"), so every TypedDict below includes them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    MANUFACTURER_PLANNER = "ManufacturerPlanner"
    RETAILER_BUYER = "RetailerBuyer"
    CATEGORY_ADVISOR = "CategoryAdvisor"
    SUPPLY_CHAIN_PLANNER = "SupplyChainPlanner"
    FINANCE_ANALYST = "FinanceAnalyst"


ALL_ROLE_NAMES: List[str] = [r.value for r in UserRole]


# ---------------------------------------------------------------------------
# Shared / per-entity enums (PRD §3)
# ---------------------------------------------------------------------------

class Channel(str, Enum):
    MASS = "MASS"
    GROCERY = "GROCERY"
    CLUB = "CLUB"
    ECOMMERCE = "ECOMMERCE"
    CONVENIENCE = "CONVENIENCE"


CHANNEL_NAMES: List[str] = [c.value for c in Channel]


class RetailerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AdvisoryScope(str, Enum):
    FULL_CATEGORY = "FULL_CATEGORY"
    MANUFACTURER_ONLY = "MANUFACTURER_ONLY"


class PlanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COUNTERED = "COUNTERED"
    ACCEPTED = "ACCEPTED"
    ACTIVATED = "ACTIVATED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


PLAN_TERMINAL_STATES: List[str] = [PlanStatus.REJECTED.value, PlanStatus.EXPIRED.value]


class PlanDecision(str, Enum):
    """Payload values for POST /jbp/plans/{id}/decide (PRD §3.1)."""
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class EventType(str, Enum):
    FEATURE = "FEATURE"
    DISPLAY = "DISPLAY"
    PRICE_REDUCTION = "PRICE_REDUCTION"
    IN_STORE_DEMO = "IN_STORE_DEMO"


class EventStatus(str, Enum):
    PENCILED = "PENCILED"
    LOCKED = "LOCKED"
    CANCELLED = "CANCELLED"


class AnalysisStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class AnalysisDecision(str, Enum):
    """Payload values for POST /jbp/category-analyses/{id}/decide (PRD §3.3)."""
    ACCEPT = "ACCEPT"
    RETURN = "RETURN"


class ShelfRecStatus(str, Enum):
    PROPOSED = "PROPOSED"
    IMPLEMENTING = "IMPLEMENTING"
    REJECTED = "REJECTED"
    VERIFIED = "VERIFIED"
    STALLED = "STALLED"
    WITHDRAWN = "WITHDRAWN"


class ShelfRecDecision(str, Enum):
    """Payload values for POST /jbp/shelf-recommendations/{id}/decide (PRD §3.4)."""
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class LaunchStatus(str, Enum):
    PLANNING = "PLANNING"
    LAUNCHED = "LAUNCHED"
    REVIEWED = "REVIEWED"
    DELISTED = "DELISTED"


class PhaseType(str, Enum):
    CAPACITY_BUILD = "CAPACITY_BUILD"
    DISTRIBUTION_BUILD = "DISTRIBUTION_BUILD"
    TRADE_SPEND = "TRADE_SPEND"
    SUSTAIN = "SUSTAIN"


# phase_index 1..4 -> phase_type, fixed at auto-creation (PRD §3.5)
PHASE_TYPE_BY_INDEX = {
    1: PhaseType.CAPACITY_BUILD.value,
    2: PhaseType.DISTRIBUTION_BUILD.value,
    3: PhaseType.TRADE_SPEND.value,
    4: PhaseType.SUSTAIN.value,
}


class PhaseStatus(str, Enum):
    PENDING = "PENDING"
    GATE_PASSED = "GATE_PASSED"
    GATE_FAILED = "GATE_FAILED"


class DeductionBucket(str, Enum):
    EDLP = "EDLP"
    EVENT = "EVENT"


class DeductionStatus(str, Enum):
    RECEIVED = "RECEIVED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"
    WRITTEN_OFF = "WRITTEN_OFF"


DEDUCTION_TERMINAL_STATES: List[str] = [
    DeductionStatus.SETTLED.value,
    DeductionStatus.REJECTED.value,
    DeductionStatus.WRITTEN_OFF.value,
]


class DeductionAction(str, Enum):
    """Payload values for POST /jbp/deductions/{id}/resolve (PRD §3.6)."""
    DISPUTE = "DISPUTE"
    SETTLE = "SETTLE"
    REJECT = "REJECT"
    WRITE_OFF = "WRITE_OFF"


class ForecastPubStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class ForecastCommitStatus(str, Enum):
    UNCOMMITTED = "UNCOMMITTED"
    COMMITTED = "COMMITTED"


class PricePackStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RETIRED = "RETIRED"


class PricePackDecision(str, Enum):
    """Payload values for POST /jbp/price-pack-decisions/{id}/decide (PRD §3.8)."""
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ReviewStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"


class ReviewDecision(str, Enum):
    """Payload values for POST /jbp/performance-reviews/{id}/finalize (PRD §3.9)."""
    CONTINUE = "CONTINUE"
    DELIST = "DELIST"


class RiskPosture(str, Enum):
    HEALTHY = "HEALTHY"
    WATCH = "WATCH"
    AT_RISK = "AT_RISK"
    DELIST_RECOMMENDED = "DELIST_RECOMMENDED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (response shapes; PRD §2.5 common fields on all thirteen)
# ---------------------------------------------------------------------------

class Retailer(TypedDict):
    id: str
    name: str
    country_code: str
    channels: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Category(TypedDict):
    id: str
    name: str
    advisory_scope: str
    created_at: str
    updated_at: str
    version: int


class JointBusinessPlan(TypedDict):
    id: str
    retailer_id: str
    category_id: str
    fiscal_year: int
    growth_target_pct: float
    weekly_baseline_cases: int
    avg_unit_net_price_cents: int
    status: str
    negotiation_round: int
    committed_growth_pct: Optional[float]
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PromotionalEvent(TypedDict):
    id: str
    plan_id: str
    name: str
    event_type: str
    start_date: str
    end_date: str
    discount_depth_pct: float
    status: str
    estimated_cost_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CategoryAnalysis(TypedDict):
    id: str
    plan_id: str
    title: str
    period_label: str
    includes_competitor_data: bool
    total_category_growth_pct: float
    manufacturer_share_pct: float
    competitor_share_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ShelfRecommendation(TypedDict):
    id: str
    plan_id: str
    title: str
    space_change_pct: float
    target_store_count: int
    sku_adds: List[str]
    sku_drops: List[str]
    status: str
    accepted_at: Optional[str]
    verified_store_count: Optional[int]
    created_at: str
    updated_at: str
    version: int


class InnovationLaunch(TypedDict):
    id: str
    plan_id: str
    product_name: str
    pack_family: str
    launch_date: str
    total_trade_budget_cents: int
    status: str
    budget_remaining_cents: int
    projected_distribution_weighted_pct: float
    projected_distribution_committed_pct: float
    launched_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LaunchPhase(TypedDict):
    id: str
    launch_id: str
    phase_index: int
    phase_type: str
    distribution_target_pct: float
    capacity_cases: int
    trade_spend_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TradeFund(TypedDict):
    id: str
    plan_id: str
    accrual_rate_pct: float
    edlp_split_pct: int
    edlp_accrued_cents: int
    event_accrued_cents: int
    edlp_cash_cents: int
    event_cash_cents: int
    event_reserved_cents: int
    edlp_settled_cents: int
    event_settled_cents: int
    total_invoiced_cents: int
    edlp_available_cents: int
    event_available_cents: int
    created_at: str
    updated_at: str
    version: int


class Deduction(TypedDict):
    id: str
    fund_id: str
    claim_reference: str
    bucket: str
    amount_cents: int
    status: str
    settled_amount_cents: Optional[int]
    short_paid: bool
    absorbed_by_manufacturer: bool
    created_at: str
    updated_at: str
    version: int


class Forecast(TypedDict):
    id: str
    plan_id: str
    week_start: str
    baseline_cases: int
    pub_status: str
    commit_status: str
    committed_cases: Optional[int]
    committed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PricePackDecisionRecord(TypedDict):
    id: str
    plan_id: str
    channel: str
    pack_family: str
    pack_code: str
    unit_count: int
    list_price_cents: int
    price_per_unit_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PerformanceReview(TypedDict):
    id: str
    launch_id: str
    period_start: str
    period_end: str
    actual_sales_cents: int
    sales_target_cents: int
    target_distribution_pct: float
    distribution_achieved_pct: float
    sales_attainment_pct: float
    forecast_bias_pct: float
    friction_count: int
    risk_score: int
    risk_posture: str
    status: str
    decision: Optional[str]
    created_at: str
    updated_at: str
    version: int
