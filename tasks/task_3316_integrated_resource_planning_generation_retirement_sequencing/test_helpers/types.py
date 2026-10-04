"""Domain types: entity TypedDicts, status enums, role enum for the IRP domain."""
from enum import Enum
from typing import TypedDict, Optional, List


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN_FOR_COMMENT = "OPEN_FOR_COMMENT"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    APPROVED_WITH_CONDITIONS = "APPROVED_WITH_CONDITIONS"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class PortfolioStatus(str, Enum):
    DRAFT = "DRAFT"
    FROZEN = "FROZEN"


class ResourceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECIDED = "DECIDED"
    RETIRED = "RETIRED"
    MOTHBALLED = "MOTHBALLED"


class ResourceType(str, Enum):
    COAL = "COAL"
    GAS_CC = "GAS_CC"
    GAS_CT = "GAS_CT"
    NUCLEAR = "NUCLEAR"
    HYDRO = "HYDRO"
    SOLAR = "SOLAR"
    WIND = "WIND"
    STORAGE = "STORAGE"
    DEMAND_RESPONSE = "DEMAND_RESPONSE"


class FuelType(str, Enum):
    COAL = "COAL"
    NATURAL_GAS = "NATURAL_GAS"
    URANIUM = "URANIUM"
    WATER = "WATER"
    SUN = "SUN"
    WIND = "WIND"
    NONE = "NONE"


class ScenarioTag(str, Enum):
    BASE = "BASE"
    HIGH_ELECTRIFICATION = "HIGH_ELECTRIFICATION"
    LOW_GROWTH = "LOW_GROWTH"


class AnalysisStatus(str, Enum):
    DRAFT = "DRAFT"
    FINAL = "FINAL"


class Recommendation(str, Enum):
    RETIRE = "RETIRE"
    KEEP = "KEEP"


class CommentStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class TestimonyStatus(str, Enum):
    FILED = "FILED"
    WITHDRAWN = "WITHDRAWN"


class CommitmentStatus(str, Enum):
    ISSUED = "ISSUED"
    AWARDED = "AWARDED"
    CANCELLED = "CANCELLED"


class ConditionStatus(str, Enum):
    OPEN = "OPEN"
    DISCHARGED = "DISCHARGED"


class PartyType(str, Enum):
    CONSUMER_ADVOCATE = "CONSUMER_ADVOCATE"
    INDUSTRIAL_GROUP = "INDUSTRIAL_GROUP"
    ENVIRONMENTAL_ORG = "ENVIRONMENTAL_ORG"
    MUNICIPALITY = "MUNICIPALITY"


class SensitivityDimension(str, Enum):
    FUEL_PRICE = "FUEL_PRICE"
    POLICY = "POLICY"
    TECHNOLOGY_COST = "TECHNOLOGY_COST"


class ScoringVariant(str, Enum):
    COST_PLUS = "COST_PLUS"
    MARKET = "MARKET"


class SnapshotVariant(str, Enum):
    COINCIDENT = "COINCIDENT"
    NET_PEAK = "NET_PEAK"


class AccreditationMode(str, Enum):
    DECIDED_EXCLUSIVE = "DECIDED_EXCLUSIVE"
    DECIDED_INCLUSIVE = "DECIDED_INCLUSIVE"


class UserRole(str, Enum):
    UTILITY_PLANNER = "UtilityPlanner"
    COMMISSIONER = "Commissioner"
    INTERVENER = "Intervener"
    PUBLIC_COMMENTER = "PublicCommenter"
    PLATFORM_ADMIN = "PlatformAdmin"


# --- Entity TypedDicts -------------------------------------------------------

class ResourcePlan(TypedDict, total=False):
    id: str
    plan_name: str
    cycle_year: int
    planning_horizon_years: int
    status: str
    comment_window_opens_on: Optional[str]
    comment_window_closes_on: Optional[str]
    submitted_on: Optional[str]
    approved_snapshot_id: Optional[str]
    preferred_portfolio_id: Optional[str]
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class LoadForecast(TypedDict, total=False):
    id: str
    plan_id: str
    scenario_tag: str
    forecast_year: int
    residential_mw: float
    commercial_mw: float
    industrial_mw: float
    electrification_mw: float
    total_peak_mw: float
    effective_load_mw: float
    locked: bool
    created_at: str
    updated_at: str
    version: int


class Resource(TypedDict, total=False):
    id: str
    unit_name: str
    resource_type: str
    nameplate_mw: float
    in_service_year: int
    fuel_type: str
    status: str
    retirement_year: Optional[int]
    decision_year: Optional[int]
    plan_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ResourcePortfolio(TypedDict, total=False):
    id: str
    plan_id: str
    portfolio_name: str
    preferred_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ResourceCandidate(TypedDict, total=False):
    id: str
    candidate_name: str
    resource_type: str
    nameplate_mw: float
    online_year: int
    capex_usd_per_kw: float
    fixed_om_usd_per_kw_year: float
    fuel_type: str
    build_lead_years: int
    global_sequence_index: int
    created_at: str
    updated_at: str
    version: int


# Append-only junction (PRD §2.5): carries only id + created_at.
class Position(TypedDict, total=False):
    id: str
    portfolio_id: str
    candidate_id: str
    committed_mw: float
    selected: bool
    created_at: str


# Computed immutable artifact (PRD §2.5): carries only id + created_at.
class ReliabilitySnapshot(TypedDict, total=False):
    id: str
    portfolio_id: str
    forecast_year: int
    scenario_tag: str
    fuel_price_usd_per_mmbtu: float
    capacity_margin_mw: float
    accredited_supply_mw: float
    load_mw: float
    meets_requirement: bool
    created_at: str


class RetirementAnalysis(TypedDict, total=False):
    id: str
    resource_id: str
    plan_id: str
    snapshot_id: str
    compliance_cost_usd: float
    replacement_cost_usd: float
    net_retirement_benefit_usd: float
    fixed_om_avoided_usd: float
    recommendation: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PublicComment(TypedDict, total=False):
    id: str
    plan_id: str
    commenter_name: str
    commenter_email: str
    body: str
    status: str
    created_at: str
    updated_at: str
    version: int


class IntervenorTestimony(TypedDict, total=False):
    id: str
    plan_id: str
    intervenor_id: str
    topic: str
    body: str
    volume_no: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Intervenor(TypedDict, total=False):
    id: str
    legal_name: str
    party_type: str
    standing_approved: bool
    created_at: str
    updated_at: str
    version: int


class SensitivityAnalysis(TypedDict, total=False):
    id: str
    plan_id: str
    snapshot_id: str
    dimension: str
    delta_pct: float
    adjusted_score_usd: float
    base_score_usd: float
    robust_flag: bool
    created_at: str
    updated_at: str
    version: int


class ProcurementCommitment(TypedDict, total=False):
    id: str
    plan_id: str
    candidate_id: str
    committed_mw: float
    solicitation_type: str
    created_by_user_id: str
    condition_discharge_ids: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanCondition(TypedDict, total=False):
    id: str
    plan_id: str
    description: str
    required_procurement_mw: float
    status: str
    created_at: str
    updated_at: str
    version: int


# Immutable periodic filing (PRD §2.5): carries only id + created_at.
class PlanDeviationReport(TypedDict, total=False):
    id: str
    plan_id: str
    report_year: int
    baseline_load_mw: float
    actual_load_mw: float
    load_deviation_pct: float
    committed_procurement_mw: float
    required_procurement_mw: float
    procurement_deviation_mw: float
    material_breach: bool
    created_at: str
