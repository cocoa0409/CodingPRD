"""TypedDict shapes and enum vocabularies for the community health assessment API.

Every declared entity carries the four common fields ``id``, ``created_at``,
``updated_at`` and ``version``.  The enum members below are exactly the values
the PRD permits; no others are legal on the wire.
"""
from __future__ import annotations

from typing import Dict, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class Role:
    COMMUNITY_BENEFIT_OFFICER = "CommunityBenefitOfficer"
    DATA_STEWARD = "DataSteward"
    BOARD_CHAIR = "BoardChair"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    PARTNER_REPRESENTATIVE = "PartnerRepresentative"
    PUBLIC_VIEWER = "PublicViewer"


ALL_ROLES = [
    Role.COMMUNITY_BENEFIT_OFFICER,
    Role.DATA_STEWARD,
    Role.BOARD_CHAIR,
    Role.COMPLIANCE_OFFICER,
    Role.PARTNER_REPRESENTATIVE,
    Role.PUBLIC_VIEWER,
]


# --------------------------------------------------------------------------
# AssessmentCycle
# --------------------------------------------------------------------------
class CycleStatus:
    DRAFT = "DRAFT"
    DATA_COLLECTION = "DATA_COLLECTION"
    INPUT_GATHERING = "INPUT_GATHERING"
    PRIORITIZATION = "PRIORITIZATION"
    STRATEGY_DEVELOPMENT = "STRATEGY_DEVELOPMENT"
    BOARD_REVIEW = "BOARD_REVIEW"
    ADOPTED = "ADOPTED"
    PUBLISHED = "PUBLISHED"
    FILED = "FILED"
    CLOSED = "CLOSED"


CYCLE_FORWARD_ORDER = [
    CycleStatus.DRAFT,
    CycleStatus.DATA_COLLECTION,
    CycleStatus.INPUT_GATHERING,
    CycleStatus.PRIORITIZATION,
    CycleStatus.STRATEGY_DEVELOPMENT,
    CycleStatus.BOARD_REVIEW,
    CycleStatus.ADOPTED,
    CycleStatus.PUBLISHED,
    CycleStatus.FILED,
    CycleStatus.CLOSED,
]


class Posture:
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class BoardActionType:
    ADOPT = "ADOPT"
    DEFER = "DEFER"


# --------------------------------------------------------------------------
# HealthIndicator / IndicatorDataPoint
# --------------------------------------------------------------------------
class IndicatorDomain:
    BEHAVIORAL_HEALTH = "BEHAVIORAL_HEALTH"
    CHRONIC_DISEASE = "CHRONIC_DISEASE"
    MATERNAL_CHILD_HEALTH = "MATERNAL_CHILD_HEALTH"
    ACCESS_TO_CARE = "ACCESS_TO_CARE"
    HOUSING_AND_FOOD = "HOUSING_AND_FOOD"


class DataState:
    SUFFICIENT = "SUFFICIENT"
    INSUFFICIENT = "INSUFFICIENT"


class DataSourceType:
    PUBLIC_DATASET = "PUBLIC_DATASET"
    HOSPITAL_EHR = "HOSPITAL_EHR"
    COMMUNITY_SURVEY = "COMMUNITY_SURVEY"
    VITAL_STATISTICS = "VITAL_STATISTICS"


class DataPointStatus:
    ACTIVE = "ACTIVE"
    VOID = "VOID"


class Subgroup:
    """``population_subgroup`` is free upper-snake-case text, not a closed enum.

    ``OVERALL`` is the one distinguished label: it feeds
    ``latest_overall_value`` and therefore ``severity_score``.
    """

    OVERALL = "OVERALL"
    BLACK_NH = "BLACK_NH"
    WHITE_NH = "WHITE_NH"
    HISPANIC = "HISPANIC"
    ASIAN_NH = "ASIAN_NH"
    LOW_INCOME = "LOW_INCOME"
    RURAL = "RURAL"


# --------------------------------------------------------------------------
# ResponsibleParty
# --------------------------------------------------------------------------
class PartyType:
    INTERNAL = "INTERNAL"
    PARTNER = "PARTNER"


# --------------------------------------------------------------------------
# StakeholderInterview
# --------------------------------------------------------------------------
class InterviewStatus:
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Sector:
    SAFETY_NET_PROVIDER = "SAFETY_NET_PROVIDER"
    PUBLIC_HEALTH_AGENCY = "PUBLIC_HEALTH_AGENCY"
    SCHOOL_DISTRICT = "SCHOOL_DISTRICT"
    FAITH_BASED = "FAITH_BASED"
    RESIDENT_COALITION = "RESIDENT_COALITION"
    PAYER = "PAYER"


# --------------------------------------------------------------------------
# PriorityCandidate
# --------------------------------------------------------------------------
class CandidateStatus:
    DRAFT = "DRAFT"
    SCORED = "SCORED"
    SELECTED = "SELECTED"
    DEFERRED = "DEFERRED"
    SCORE_INVALIDATED = "SCORE_INVALIDATED"


class ScoringVariant:
    EQUAL_WEIGHT = "EQUAL_WEIGHT"
    COMMUNITY_WEIGHTED = "COMMUNITY_WEIGHTED"


# --------------------------------------------------------------------------
# ImplementationStrategy / StrategyObjective
# --------------------------------------------------------------------------
class ApprovalState:
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    RETURNED = "RETURNED"
    SUPERSEDED = "SUPERSEDED"


class ExecutionState:
    NOT_STARTED = "NOT_STARTED"
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    BEHIND = "BEHIND"
    SUSPENDED_PENDING_REVIEW = "SUSPENDED_PENDING_REVIEW"
    COMPLETED = "COMPLETED"
    DISCONTINUED = "DISCONTINUED"
    CLOSED_OUT = "CLOSED_OUT"


class ObjectiveStatus:
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    REVISED = "REVISED"
    FINALIZED_MET = "FINALIZED_MET"
    FINALIZED_NOT_MET = "FINALIZED_NOT_MET"


class AttainmentStatus:
    PENDING = "PENDING"
    NOT_MET = "NOT_MET"
    PARTIAL = "PARTIAL"
    MET = "MET"


# --------------------------------------------------------------------------
# PartnershipAgreement / ResourceCommitment
# --------------------------------------------------------------------------
class SignatureState:
    NEGOTIATING = "NEGOTIATING"
    HOSPITAL_SIGNED = "HOSPITAL_SIGNED"
    PARTNER_SIGNED = "PARTNER_SIGNED"
    EXECUTED = "EXECUTED"
    TERMINATED = "TERMINATED"


class FundingState:
    UNFUNDED = "UNFUNDED"
    PLEDGED = "PLEDGED"
    FUNDED = "FUNDED"
    RELEASED = "RELEASED"


class SignatorySide:
    HOSPITAL = "HOSPITAL"
    PARTNER = "PARTNER"


class CommitmentStatus:
    PENDING = "PENDING"
    COMMITTED = "COMMITTED"
    RELEASED = "RELEASED"


# --------------------------------------------------------------------------
# CommunityBenefitReport / ExpensePosting
# --------------------------------------------------------------------------
class ReportStatus:
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    FILED = "FILED"


class ValuationBasis:
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class PostingStatus:
    POSTED = "POSTED"
    VOID = "VOID"


class Category:
    FINANCIAL_ASSISTANCE = "FINANCIAL_ASSISTANCE"
    SUBSIDIZED_SERVICES = "SUBSIDIZED_SERVICES"
    COMMUNITY_HEALTH_IMPROVEMENT = "COMMUNITY_HEALTH_IMPROVEMENT"
    CASH_AND_INKIND = "CASH_AND_INKIND"
    COMMUNITY_BUILDING = "COMMUNITY_BUILDING"


CHARGE_BASED_CATEGORIES = [Category.FINANCIAL_ASSISTANCE, Category.SUBSIDIZED_SERVICES]
COST_BASED_CATEGORIES = [
    Category.COMMUNITY_HEALTH_IMPROVEMENT,
    Category.CASH_AND_INKIND,
    Category.COMMUNITY_BUILDING,
]

CATEGORY_TOTAL_FIELD = {
    Category.FINANCIAL_ASSISTANCE: "financial_assistance_cents",
    Category.SUBSIDIZED_SERVICES: "subsidized_services_cents",
    Category.COMMUNITY_HEALTH_IMPROVEMENT: "community_health_improvement_cents",
    Category.CASH_AND_INKIND: "cash_and_inkind_cents",
    Category.COMMUNITY_BUILDING: "community_building_cents",
}


# --------------------------------------------------------------------------
# ProgressEvaluation
# --------------------------------------------------------------------------
class EvalType:
    ANNUAL = "ANNUAL"
    MID_CYCLE = "MID_CYCLE"


class EvalStatus:
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"


# --------------------------------------------------------------------------
# Entity response shapes
# --------------------------------------------------------------------------
class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class AssessmentCycle(CommonFields, total=False):
    fiscal_year: int
    service_area_name: str
    prior_year_cost_to_charge_ratio: float
    total_operating_expense_cents: int
    status: str
    posture: str
    completed_interview_count: int
    sufficient_indicator_count: int
    selected_priority_count: int
    review_flag_count: int
    board_deferral_count: int
    mid_cycle_adjustment_count: int
    annual_report_count: int
    adopted_at: Optional[str]
    adoption_board_user_id: Optional[str]
    votes_for_at_adoption: Optional[int]
    votes_against_at_adoption: Optional[int]
    public_url: Optional[str]
    public_comment_channel: Optional[str]
    public_availability_met: bool
    published_at: Optional[str]
    return_form_id: Optional[str]
    filed_at: Optional[str]


class HealthIndicator(CommonFields, total=False):
    cycle_id: str
    domain: str
    name: str
    benchmark_value: float
    latest_overall_value: Optional[float]
    severity_score: Optional[float]
    disparity_ratio: Optional[float]
    subgroup_count: int
    evidence_count: int
    data_state: str


class IndicatorDataPoint(CommonFields, total=False):
    indicator_id: str
    population_subgroup: str
    source_type: str
    value: float
    collected_on: str
    status: str
    void_reason: Optional[str]
    voided_by_user_id: Optional[str]


class ResponsibleParty(CommonFields, total=False):
    name: str
    party_type: str
    fte_capacity_bp: int
    committed_fte_bp: int


class StakeholderInterview(CommonFields, total=False):
    cycle_id: str
    facilitator_party_id: str
    organization_name: str
    sector: str
    starts_at: str
    ends_at: str
    status: str
    concern_ratings: Optional[Dict[str, int]]
    attendee_count: Optional[int]
    completed_at: Optional[str]
    cancel_reason: Optional[str]


class PriorityCandidate(CommonFields, total=False):
    cycle_id: str
    indicator_id: str
    hospital_capacity_score: float
    scoring_variant: Optional[str]
    severity_input: Optional[float]
    disparity_points: Optional[float]
    community_concern_index: Optional[float]
    composite_score: Optional[float]
    status: str
    concern_input_dirty: bool
    selection_rationale: Optional[str]
    defer_reason: Optional[str]
    strategy_count: int


class ImplementationStrategy(CommonFields, total=False):
    candidate_id: str
    title: str
    authorized_budget_cents: int
    budget_available_cents: int
    approval_state: str
    execution_state: str
    superseded_by_strategy_id: Optional[str]
    submitted_at: Optional[str]
    approved_at: Optional[str]
    active_objective_count: int
    execution_note: Optional[str]


class StrategyObjective(CommonFields, total=False):
    strategy_id: str
    metric_name: str
    baseline_value: float
    target_value: float
    target_date: str
    actual_value: Optional[float]
    as_of_date: Optional[str]
    attainment_pct: Optional[float]
    attainment_status: str
    status: str
    baseline_locked_at: Optional[str]


class PartnershipAgreement(CommonFields, total=False):
    cycle_id: str
    party_id: str
    pledged_cents: int
    funded_cents: int
    accountability_metric: str
    shared_accountability_pct: float
    term_start: str
    term_end: str
    signature_state: str
    funding_state: str
    hospital_signed_at: Optional[str]
    partner_signed_at: Optional[str]
    hospital_signatory_user_id: Optional[str]
    partner_signatory_user_id: Optional[str]
    terminate_reason: Optional[str]


class ResourceCommitment(CommonFields, total=False):
    strategy_id: str
    party_id: str
    partnership_id: Optional[str]
    fte_bp: int
    funding_cents: int
    effective_from: str
    effective_to: str
    status: str
    committed_at: Optional[str]
    released_at: Optional[str]
    release_reason: Optional[str]


class CommunityBenefitReport(CommonFields, total=False):
    cycle_id: str
    fiscal_year: int
    valuation_basis: str
    cost_to_charge_ratio: Optional[float]
    audited_cost_to_charge_ratio: Optional[float]
    status: str
    financial_assistance_cents: int
    subsidized_services_cents: int
    community_health_improvement_cents: int
    cash_and_inkind_cents: int
    community_building_cents: int
    total_valued_cents: int
    overhead_rate: float
    indirect_allocation_cents: int
    grand_total_cents: int
    benefit_pct_of_expense: float
    created_by_user_id: str
    finalized_by_user_id: Optional[str]
    locked_at: Optional[str]
    filed_at: Optional[str]


class ExpensePosting(CommonFields, total=False):
    report_id: str
    strategy_id: Optional[str]
    category: str
    charges_cents: int
    direct_cost_cents: int
    valued_cents: int
    valuation_basis_at_posting: str
    ratio_applied: Optional[float]
    status: str
    posted_by_user_id: str
    void_reason: Optional[str]
    voided_by_user_id: Optional[str]


class ProgressEvaluation(CommonFields, total=False):
    cycle_id: str
    eval_type: str
    period_year: int
    findings_summary: Optional[str]
    status: str
    public_url: Optional[str]
    published_at: Optional[str]
    objectives_revised_count: int
