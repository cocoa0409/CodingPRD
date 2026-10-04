"""Domain types: entity TypedDicts, status enums, role enum.

Field names and enum members follow the PRD exactly. Entities other than
QualificationRun carry id, created_at, updated_at, and version; QualificationRun
is an immutable event record carrying only id and created_at.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Role enum (PRD §2.1 — six roles, spelled exactly) ──────────────────────

class UserRole(str, Enum):
    PORTFOLIO_MANAGER = "PortfolioManager"
    BRAND_MANAGER = "BrandManager"
    PLANT_DIRECTOR = "PlantDirector"
    RETAILER_BUYER = "RetailerBuyer"
    SUPPLY_CHAIN_PLANNER = "SupplyChainPlanner"
    FINANCE_CONTROLLER = "FinanceController"


# ─── Status / value enums ────────────────────────────────────────────────────

class BrandStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNDER_REVIEW = "UNDER_REVIEW"
    DIVESTING = "DIVESTING"
    DIVESTED = "DIVESTED"
    EXITED = "EXITED"


class ItemStatus(str, Enum):
    LISTED = "LISTED"
    CUT_PROPOSED = "CUT_PROPOSED"
    SELL_THROUGH = "SELL_THROUGH"
    DISCONTINUED = "DISCONTINUED"


class PlantStatus(str, Enum):
    OPERATING = "OPERATING"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"


class RiskRating(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class CaseStatus(str, Enum):
    SCORED = "SCORED"
    EXECUTING = "EXECUTING"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    VOIDED = "VOIDED"


class Recommendation(str, Enum):
    CUT = "CUT"
    KEEP = "KEEP"


class CaseDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class DivestitureStatus(str, Enum):
    PROPOSED = "PROPOSED"
    SPA_SIGNED = "SPA_SIGNED"
    CLOSED = "CLOSED"
    SEPARATED = "SEPARATED"


class TsaStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class TransferStatus(str, Enum):
    PLANNED = "PLANNED"
    QUALIFYING = "QUALIFYING"
    EXECUTED = "EXECUTED"


class RunResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class NegotiationStatus(str, Enum):
    TERMS_PROPOSED = "TERMS_PROPOSED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class NegotiationResponse(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class CycleStatus(str, Enum):
    ALLOCATING = "ALLOCATING"
    LOCKED = "LOCKED"


class ProjectStatus(str, Enum):
    PROPOSED = "PROPOSED"
    FUNDED = "FUNDED"
    DEFERRED = "DEFERRED"


# ─── Entity TypedDicts ───────────────────────────────────────────────────────
# All entities except QualificationRun: id + created_at + updated_at + version.
# Nullable system fields (e.g. sell_through_deadline) are present-but-null.

class Brand(TypedDict):
    id: str
    name: str
    category_name: str
    core_flag: bool
    private_label_share_pct: int
    annual_net_revenue_cents: int
    brand_status: str
    created_at: str
    updated_at: str
    version: int


class Item(TypedDict):
    id: str
    brand_id: str
    primary_plant_id: str
    sku_code: str
    annual_units: int
    unit_net_revenue_cents: int
    unit_cost_cents: int
    units_on_hand: int
    salvageable: bool
    item_status: str
    sell_through_deadline: Optional[str]
    units_sold_cumulative: int
    units_written_off_cumulative: int
    obsolescence_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class Plant(TypedDict):
    id: str
    name: str
    quarterly_capacity_units: int
    plant_status: str
    closure_date: Optional[str]
    committed_units_per_quarter: int
    utilization_pct: float
    created_at: str
    updated_at: str
    version: int


class Retailer(TypedDict):
    id: str
    name: str
    risk_rating: str
    created_at: str
    updated_at: str
    version: int


class RationalizationCase(TypedDict):
    id: str
    item_id: str
    proposer_user_id: str
    volume_score: float
    margin_score: float
    shelf_resilience_score: float
    backlash_resilience_score: float
    composite_score: float
    recommendation: str
    case_status: str
    decider_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Divestiture(TypedDict):
    id: str
    brand_id: str
    acquirer_name: str
    headline_price_cents: int
    expected_close_date: str
    divestiture_status: str
    created_at: str
    updated_at: str
    version: int


class TransitionServiceAgreement(TypedDict):
    id: str
    divestiture_id: str
    monthly_fee_cents: int
    start_date: str
    end_date: str
    tsa_status: str
    terminated_at: Optional[str]
    early_termination_penalty_cents: int
    created_at: str
    updated_at: str
    version: int


class ProductTransfer(TypedDict):
    id: str
    item_id: str
    source_plant_id: str
    target_plant_id: str
    transfer_status: str
    consecutive_pass_count: int
    created_at: str
    updated_at: str
    version: int


class QualificationRun(TypedDict):
    # Immutable event record: carries ONLY id and created_at as common fields.
    # updated_at and version are absent by design.
    id: str
    transfer_id: str
    run_date: str
    units_produced: int
    units_rejected: int
    result: str
    certifier_plant_id: str
    created_at: str


class BrandTerm(TypedDict):
    brand_id: str
    baseline_facings: int
    proposed_facings: int


class CombinedNegotiation(TypedDict):
    id: str
    retailer_id: str
    period_code: str
    brand_terms: List[BrandTerm]
    effective_from: str
    effective_to: str
    total_baseline_facings: int
    total_proposed_facings: int
    shelf_reduction_pct: float
    negotiation_status: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class CapitalCycle(TypedDict):
    id: str
    period_code: str
    total_capital_cents: int
    window_start: str
    window_end: str
    allocated_cents: int
    remaining_cents: int
    cycle_status: str
    created_at: str
    updated_at: str
    version: int


class InnovationProject(TypedDict):
    id: str
    brand_id: str
    funding_cycle_id: str
    title: str
    requested_capital_cents: int
    expected_revenue_cents_year3: int
    strategic_fit_score: int
    priority_score: float
    project_status: str
    created_at: str
    updated_at: str
    version: int
