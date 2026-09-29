"""Entity shapes, status vocabularies and role names declared by the PRD."""

from typing import Any, Dict, List, Optional, TypedDict

# Resources are returned as plain JSON objects; the TypedDicts below document
# the field sets the PRD declares. total=False everywhere because reads of a
# freshly created row may legitimately carry nulls.

JsonDict = Dict[str, Any]


class Student(TypedDict, total=False):
    id: str
    student_number: str
    first_name: str
    last_name: str
    grade_band: str
    primary_disability: str
    iep_weekly_minutes_total: int
    transportation_required: bool
    home_school_code: str
    esy_eligibility_status: str
    pending_award_minutes: int
    outstanding_owed_minutes: int
    delivered_makeup_minutes_total: int
    esy_service_alert: bool
    stay_put_active: bool
    created_at: str
    updated_at: str
    version: int


class SkillProbe(TypedDict, total=False):
    skill_domain: str
    pre_break_mastery_pct: int
    post_break_mastery_pct: int
    recoupment_days_observed: int
    trials_count: int


class EligibilityDetermination(TypedDict, total=False):
    id: str
    student_id: str
    school_year: str
    analysis_variant: str
    skill_probes: List[SkillProbe]
    status: str
    max_regression_pct: Optional[float]
    max_recoupment_days: Optional[int]
    criteria_met_count: int
    data_sufficiency: Optional[str]
    eligibility_recommendation: Optional[str]
    objection_round_count: int
    analyzed_by_user_id: Optional[str]
    finalized_by_user_id: Optional[str]
    parent_comment: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EsyProgram(TypedDict, total=False):
    id: str
    name: str
    school_year: str
    session_start_date: str
    session_end_date: str
    instructional_weekdays: List[str]
    blackout_dates: List[str]
    cancelled_dates: List[str]
    daily_minutes_cap: int
    instructional_days_count: int
    instructional_week_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Provider(TypedDict, total=False):
    id: str
    full_name: str
    role_type: str
    credential_expires_on: str
    rate_cents_per_minute: int
    max_weekly_minutes: int
    assigned_weekly_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceCommitment(TypedDict, total=False):
    id: str
    program_id: str
    student_id: str
    transportation_run_id: Optional[str]
    service_type: str
    iep_weekly_minutes: int
    staffing_ratio: str
    planned_total_minutes: int
    weekly_minutes_committed: int
    daily_minutes: int
    delivered_minutes: int
    compensable_owed_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ProviderAssignment(TypedDict, total=False):
    id: str
    commitment_id: str
    provider_id: str
    weekday: str
    start_time: str
    end_time: str
    effective_from: str
    effective_to: str
    covered_weekly_minutes: int
    covered_total_minutes: int
    base_cost_cents: int
    indirect_cost_cents: int
    total_charge_cents: int
    charged_fund_source: Optional[str]
    charged_budget_code: Optional[str]
    status: str
    release_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransportationRun(TypedDict, total=False):
    id: str
    program_id: str
    route_code: str
    service_date: str
    window_start_time: str
    window_end_time: str
    vehicle_capacity_seats: int
    seats_committed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceLog(TypedDict, total=False):
    id: str
    commitment_id: str
    provider_id: Optional[str]
    service_date: str
    outcome: str
    minutes_scheduled: int
    minutes_delivered: int
    miss_reason_code: Optional[str]
    status: str
    generated_by: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompensatoryAward(TypedDict, total=False):
    id: str
    student_id: str
    source_program_id: str
    calculation_variant: str
    computed_minutes: int
    proposed_minutes: Optional[int]
    agreed_minutes: Optional[int]
    delivered_minutes: int
    scheduled_minutes: int
    remaining_owed_minutes: int
    forfeited_minutes: int
    negotiation_status: str
    delivery_status: str
    dispute_round_count: int
    parent_no_show_count: int
    delivery_deadline_date: Optional[str]
    severity_factor: float
    verified_missed_log_count: int
    excluded_log_count: int
    authored_by_user_id: Optional[str]
    resolved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MakeupSession(TypedDict, total=False):
    id: str
    award_id: str
    provider_id: str
    supersedes_session_id: Optional[str]
    session_date: str
    start_time: str
    end_time: str
    minutes_planned: int
    minutes_delivered: Optional[int]
    status: str
    charge_cents: int
    charged_fund_source: Optional[str]
    charged_budget_code: Optional[str]
    outcome_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundAllocation(TypedDict, total=False):
    id: str
    program_id: str
    fund_source: str
    budget_code: str
    authorized_amount_cents: int
    encumbered_amount_cents: int
    expended_amount_cents: int
    compensatory_expended_cents: int
    available_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class DueProcessRecord(TypedDict, total=False):
    id: str
    student_id: str
    record_type: str
    filed_on: str
    allegation_summary: str
    status: str
    stay_put_active: bool
    resolution_note: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# --- Status vocabularies (PRD 3) -----------------------------------------

ESY_ELIGIBILITY_STATUSES = (
    "NOT_DETERMINED",
    "ELIGIBLE",
    "INELIGIBLE",
    "PENDING_DATA",
)

DETERMINATION_STATUSES = (
    "DRAFT",
    "PARENT_REVIEW",
    "PARENT_AGREED",
    "FINALIZED",
    "WITHDRAWN",
)

ANALYSIS_VARIANTS = ("PROBE_BASED", "TEAM_JUDGMENT")

SKILL_DOMAINS = (
    "READING_FLUENCY",
    "MATH_COMPUTATION",
    "EXPRESSIVE_LANGUAGE",
    "SELF_REGULATION",
    "ADAPTIVE_SKILLS",
)

DATA_SUFFICIENCY_VALUES = ("SUFFICIENT", "INSUFFICIENT")

ELIGIBILITY_RECOMMENDATIONS = ("ELIGIBLE", "INELIGIBLE", "PENDING_DATA")

PROGRAM_STATUSES = ("PLANNING", "STAFFING_LOCKED", "OPEN", "CLOSED")

WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI")

GRADE_BANDS = ("PRE_K", "K_5", "MS_6_8", "HS_9_12", "POST_SECONDARY_18_21")

PROVIDER_ROLE_TYPES = (
    "SPED_TEACHER",
    "SLP",
    "OT",
    "PT",
    "COUNSELOR",
    "PARAEDUCATOR",
)

PROVIDER_STATUSES = ("ACTIVE", "ON_LEAVE", "INACTIVE")

SERVICE_TYPES = (
    "SPECIALIZED_INSTRUCTION",
    "SPEECH",
    "OT",
    "PT",
    "COUNSELING",
)

STAFFING_RATIOS = ("ONE_TO_ONE", "ONE_TO_THREE", "ONE_TO_SIX", "GROUP_TEN")

COMMITMENT_STATUSES = (
    "PLANNED",
    "ASSIGNED",
    "ACTIVE",
    "SUSPENDED",
    "COMPLETED",
    "TERMINATED",
)

ASSIGNMENT_STATUSES = ("ACTIVE", "RELEASED", "SUPERSEDED")

RELEASE_REASONS = (
    "SUPERSEDED_BY_NEW_ASSIGNMENT",
    "PROGRAM_CLOSED",
    "COMMITMENT_TERMINATED",
)

RUN_STATUSES = ("SCHEDULED", "CANCELLED")

SERVICE_LOG_OUTCOMES = (
    "DELIVERED",
    "PARTIAL",
    "MISSED_DISTRICT",
    "MISSED_PARENT",
    "MISSED_STUDENT_ABSENT",
)

MISS_REASON_CODES = (
    "WEATHER",
    "STAFF_ABSENCE",
    "TRANSPORT_FAILURE",
    "PARENT_CANCELLED",
    "STUDENT_ILL",
    "OTHER",
)

SERVICE_LOG_STATUSES = ("VERIFIED", "VOIDED")

GENERATED_BY_VALUES = ("PROVIDER", "CASE_MANAGER", "SYSTEM_DAY_CANCELLATION")

CALCULATION_VARIANTS = ("MINUTE_FOR_MINUTE", "QUALITATIVE_BENEFIT")

NEGOTIATION_STATUSES = (
    "DRAFT",
    "PARENT_REVIEW",
    "DISPUTED",
    "MEDIATION",
    "AGREED",
    "DECLINED",
    "CLOSED",
)

DELIVERY_STATUSES = (
    "NOT_STARTED",
    "SCHEDULING",
    "IN_PROGRESS",
    "FULFILLED",
    "LAPSED",
)

MAKEUP_SESSION_STATUSES = (
    "SCHEDULED",
    "DELIVERED",
    "NO_SHOW_PARENT",
    "CANCELLED_DISTRICT",
    "SUPERSEDED",
    "VOIDED",
)

FUND_SOURCES = ("IDEA_611_FEDERAL", "IDEA_619_FEDERAL", "LOCAL_GENERAL")

FUND_ALLOCATION_STATUSES = ("OPEN", "FROZEN", "CLOSED")

DUE_PROCESS_RECORD_TYPES = (
    "COMPLAINT",
    "DUE_PROCESS_HEARING",
    "MEDIATION_AGREEMENT",
)

DUE_PROCESS_STATUSES = ("OPEN", "RESOLVED", "DISMISSED")
