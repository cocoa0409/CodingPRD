"""TypedDict shapes and status enums for the Consulting Bench Management API.

Field lists mirror PRD §3 exactly. Every entity except HiringForecast carries the
common fields id / created_at / updated_at / version (PRD §2.4); HiringForecast
carries only id and created_at.
"""

from typing import Any, Dict, List, Optional, TypedDict


# --- Role names (PRD §2.1) ---------------------------------------------------
class Role:
    SALES_LEAD = "SalesLead"
    RESOURCE_MANAGER = "ResourceManager"
    PRACTICE_PARTNER = "PracticePartner"
    FINANCE_CONTROLLER = "FinanceController"
    CONSULTANT = "Consultant"


ALL_ROLES = (
    Role.SALES_LEAD,
    Role.RESOURCE_MANAGER,
    Role.PRACTICE_PARTNER,
    Role.FINANCE_CONTROLLER,
    Role.CONSULTANT,
)


# --- Enumerations (PRD §3) --------------------------------------------------
class Posture:
    OPEN = "OPEN"
    CONSTRAINED = "CONSTRAINED"
    FROZEN = "FROZEN"


class AvailabilityStatus:
    ASSIGNED = "ASSIGNED"
    BENCH = "BENCH"
    RESKILLING = "RESKILLING"
    INTERNAL_PROJECT = "INTERNAL_PROJECT"
    SEPARATED = "SEPARATED"


class AssertionStatus:
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class PipelineStatus:
    QUALIFYING = "QUALIFYING"
    QUALIFIED = "QUALIFIED"
    CLOSED_WON = "CLOSED_WON"
    CLOSED_LOST = "CLOSED_LOST"


class StaffingMode:
    INTERNAL = "INTERNAL"
    EXTERNAL = "EXTERNAL"


class StaffingStatus:
    UNSTAFFED = "UNSTAFFED"
    INTERNAL_STAFFING = "INTERNAL_STAFFING"
    EXTERNAL_SOURCING = "EXTERNAL_SOURCING"
    PARTIALLY_COVERED = "PARTIALLY_COVERED"
    COVERED = "COVERED"


class ClosedOutcome:
    WON = "WON"
    LOST = "LOST"


class AssignmentStatus:
    PROPOSED = "PROPOSED"
    CONFIRMED = "CONFIRMED"
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    CANCELLED = "CANCELLED"


class AssignmentCategory:
    BILLABLE = "BILLABLE"
    INVESTMENT = "INVESTMENT"


class BenchSpellState:
    MONITORING = "MONITORING"
    ESCALATED_L1 = "ESCALATED_L1"
    ESCALATED_L2 = "ESCALATED_L2"
    RESKILLING = "RESKILLING"
    INTERNAL_PROJECT = "INTERNAL_PROJECT"
    SEPARATION_PROPOSED = "SEPARATION_PROPOSED"
    CLOSED = "CLOSED"
    SEPARATED = "SEPARATED"


class SeparationDecision:
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ProgramStatus:
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"


class FirmApprovalStatus:
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"


class PlacementStatus:
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class ApprovalTier:
    NONE = "NONE"
    L1_PRACTICE_PARTNER = "L1_PRACTICE_PARTNER"
    L2_FINANCE = "L2_FINANCE"


class ApprovalStatus:
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ApprovalDecision:
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PeriodStatus:
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ForecastBasis:
    WEIGHTED = "WEIGHTED"
    COMMITTED = "COMMITTED"


class SkillFamily:
    CLOUD = "CLOUD"
    DATA = "DATA"
    SECURITY = "SECURITY"
    ERP = "ERP"
    AI = "AI"


class Level:
    ANALYST = "ANALYST"
    CONSULTANT = "CONSULTANT"
    SENIOR_CONSULTANT = "SENIOR_CONSULTANT"
    MANAGER = "MANAGER"
    PRINCIPAL = "PRINCIPAL"


class Geography:
    NA = "NA"
    EMEA = "EMEA"
    APAC = "APAC"
    LATAM = "LATAM"


# --- Common field bases (PRD §2.4) -----------------------------------------
class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


# --- Entity shapes (PRD §3) ------------------------------------------------
class PracticeGroup(CommonFields):
    name: str
    geography_code: str
    parent_group_id: Optional[str]
    external_sourcing_cap_pct: float
    level_targets: Dict[str, Any]
    total_headcount: int
    bench_headcount: int
    escalated_l2_count: int
    own_bench_ratio: float
    rollup_bench_ratio: float
    posture: str


class Skill(CommonFields):
    code: str
    name: str
    family: str
    scarcity_index: float
    retired: bool


class Consultant(CommonFields):
    full_name: str
    email: str
    level: str
    practice_group_id: str
    home_city: str
    home_geo_code: str
    cost_rate_usd_per_hour: float
    standard_bill_rate_usd_per_hour: float
    travel_max_nights_per_week: int
    travel_willing_international: bool
    development_goal_skill_id: Optional[str]
    industry_experience: List[Dict[str, Any]]
    availability_status: str
    allocated_pct: float
    separated_on: Optional[str]


class SkillAssertion(CommonFields):
    consultant_id: str
    skill_id: str
    proficiency_level: int
    certification_code: Optional[str]
    certification_expires_on: Optional[str]
    last_used_on: Optional[str]
    assertion_status: str


class DemandOpportunity(CommonFields):
    client_name: str
    practice_group_id: str
    required_skill_id: str
    min_proficiency_level: int
    required_fte: float
    win_probability_pct: int
    start_date: str
    end_date: str
    industry_code: str
    onsite_nights_per_week: int
    is_international: bool
    standard_rate_usd_per_hour: float
    requested_rate_usd_per_hour: float
    approved_rate_usd_per_hour: Optional[float]
    effective_rate_usd_per_hour: float
    pipeline_status: str
    staffing_mode: Optional[str]
    staffing_status: str
    covered_internal_fte: float
    covered_external_fte: float
    open_fte: float
    weighted_fte: float
    booked_realization_pct: float
    earned_realization_pct: Optional[float]
    blended_cost_rate_usd_per_hour: float
    blended_margin_pct: Optional[float]
    margin_breach: bool
    closed_outcome: Optional[str]


class Assignment(CommonFields):
    consultant_id: str
    demand_opportunity_id: str
    allocation_pct: float
    start_date: str
    end_date: str
    category: str
    bill_rate_usd_per_hour: float
    cost_rate_usd_per_hour: float
    match_score: float
    status: str
    confirmed_on: Optional[str]
    activated_on: Optional[str]
    released_on: Optional[str]


class BenchSpell(CommonFields):
    consultant_id: str
    started_on: str
    age_reset_on: Optional[str]
    ended_on: Optional[str]
    state: str
    escalation_count: int
    age_days: int
    reskilling_program_id: Optional[str]
    internal_project_code: Optional[str]
    investment_started_on: Optional[str]
    investment_ended_on: Optional[str]
    separation_proposed_by_user_id: Optional[str]
    separation_decided_by_user_id: Optional[str]
    separation_decision: Optional[str]


class ReskillingProgram(CommonFields):
    skill_id: str
    target_proficiency_level: int
    cohort_start_on: str
    cohort_end_on: str
    seat_capacity: int
    seats_taken: int
    cooldown_days: int
    status: str


class SubcontractorFirm(CommonFields):
    name: str
    geo_code: str
    max_concurrent_placements: int
    markup_pct: float
    pass_through_rate_usd_per_hour: float
    approval_status: str
    active_placements_count: int


class ExternalPlacement(CommonFields):
    subcontractor_firm_id: str
    demand_opportunity_id: str
    fte: float
    start_date: str
    end_date: str
    pass_through_rate_usd_per_hour: float
    bill_rate_usd_per_hour: float
    status: str
    terminated_on: Optional[str]


class DiscountApproval(CommonFields):
    demand_opportunity_id: str
    requested_rate_usd_per_hour: float
    standard_rate_usd_per_hour: float
    discount_pct: float
    provisional_realization_pct: float
    blended_cost_rate_usd_per_hour: float
    projected_margin_pct: float
    required_tier: str
    tier_escalated: bool
    status: str
    requested_by_user_id: str
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    revision_count: int


class UtilizationPeriod(CommonFields):
    consultant_id: str
    period_start_on: str
    period_end_on: str
    holiday_hours: float
    period_workdays: int
    capacity_hours: float
    net_available_hours: float
    billable_hours: float
    investment_hours: float
    bench_hours: float
    hour_overallocated: bool
    target_utilization_pct: float
    utilization_pct_target_basis: float
    utilization_pct_available_basis: Optional[float]
    utilization_pct_of_record: float
    variance_pp: float
    status: str


class HiringForecast(TypedDict):
    """PRD §2.4: HiringForecast is the sole entity without updated_at or version."""

    id: str
    created_at: str
    skill_code: str
    geography_code: str
    horizon_start_on: str
    horizon_end_on: str
    basis: str
    weighted_demand_fte: float
    internal_supply_fte: float
    external_supply_fte: float
    gap_fte: float
    recommended_hires: int
    generated_at: str
