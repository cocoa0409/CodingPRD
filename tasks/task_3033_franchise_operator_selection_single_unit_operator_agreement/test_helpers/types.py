"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class CandidateStatus(str, Enum):
    REGISTERED = "REGISTERED"
    IN_SELECTION = "IN_SELECTION"
    SELECTED = "SELECTED"
    WITHDRAWN = "WITHDRAWN"
    DISQUALIFIED = "DISQUALIFIED"


class ApplicationStage(str, Enum):
    SUBMITTED = "SUBMITTED"
    SCREENING = "SCREENING"
    INTERVIEWS = "INTERVIEWS"
    BUSINESS_ASSESSMENT = "BUSINESS_ASSESSMENT"
    IN_RESTAURANT = "IN_RESTAURANT"
    COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"


class InterviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SUBMITTED = "SUBMITTED"
    CANCELLED = "CANCELLED"


class AssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    EVALUATED = "EVALUATED"


class Verdict(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


class CommitteeDecision(str, Enum):
    NONE = "NONE"
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class RestaurantStatus(str, Enum):
    PIPELINE = "PIPELINE"
    AVAILABLE = "AVAILABLE"
    ASSIGNED = "ASSIGNED"
    TRANSITION = "TRANSITION"


class ExperienceStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SHORTFALL = "SHORTFALL"
    CANCELLED = "CANCELLED"


class OperatorStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXITING = "EXITING"
    EXITED = "EXITED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    EXECUTED = "EXECUTED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class WeekStatus(str, Enum):
    PLANNED = "PLANNED"
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ScorecardStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    DISPUTED = "DISPUTED"
    FINAL = "FINAL"


class Rating(str, Enum):
    EXCEEDS = "EXCEEDS"
    MEETS = "MEETS"
    BELOW = "BELOW"
    CRITICAL = "CRITICAL"


class RelocationKind(str, Enum):
    RELOCATION = "RELOCATION"
    SECOND_LOCATION = "SECOND_LOCATION"


class RelocationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    COMMITTEE_REVIEW = "COMMITTEE_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class ExitReason(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    INVOLUNTARY = "INVOLUNTARY"
    NON_RENEWAL = "NON_RENEWAL"


class ExitStatus(str, Enum):
    OPEN = "OPEN"
    SUCCESSOR_PENDING = "SUCCESSOR_PENDING"
    SUCCESSOR_APPROVED = "SUCCESSOR_APPROVED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StatementKind(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class StatementStatus(str, Enum):
    ISSUED = "ISSUED"
    SETTLED = "SETTLED"
    VOID = "VOID"


class VoteValue(str, Enum):
    FOR = "FOR"
    AGAINST = "AGAINST"


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    CANDIDATE = "Candidate"
    FIELD_CONSULTANT = "FieldConsultant"
    SELECTION_COMMITTEE = "SelectionCommittee"
    OPERATOR = "Operator"
    FINANCE_ADMIN = "FinanceAdmin"


class Candidate(TypedDict, total=False):
    id: str
    legal_name: str
    email: str
    home_market_code: str
    relocation_willing: bool
    liquid_capital_cents: int
    candidate_status: str
    active_application_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Application(TypedDict, total=False):
    id: str
    candidate_id: str
    target_market_code: str
    stage: str
    screening_score: Optional[int]
    interview_average: Optional[float]
    assessment_verdict: str
    experience_verdict: str
    committee_decision: str
    application_fee_cents: Optional[int]
    submitted_at: str
    created_at: str
    updated_at: str
    version: int


class InterviewRound(TypedDict, total=False):
    id: str
    application_id: str
    round_index: int
    interviewer_id: str
    scheduled_for: str
    score: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class BusinessAssessment(TypedDict, total=False):
    id: str
    application_id: str
    market_plan_text: str
    financial_projection_cents: int
    rubric_score: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Restaurant(TypedDict, total=False):
    id: str
    site_code: str
    market_code: str
    baseline_weekly_revenue_cents: int
    restaurant_status: str
    current_operator_id: Optional[str]
    equipment_value_cents: int
    sunday_closed: bool
    created_at: str
    updated_at: str
    version: int


class InRestaurantExperience(TypedDict, total=False):
    id: str
    application_id: str
    host_restaurant_id: str
    starts_on: str
    ends_on: str
    required_shift_count: int
    completed_shift_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Operator(TypedDict, total=False):
    id: str
    candidate_id: str
    agreement_id: str
    restaurant_id: str
    operator_status: str
    residency_verified: bool
    full_time_attested: bool
    lifetime_revenue_share_cents: int
    created_at: str
    updated_at: str
    version: int


class OperatorAgreement(TypedDict, total=False):
    id: str
    operator_id: str
    restaurant_id: str
    transferable: bool
    equity_stake_bps: int
    base_share_bps: int
    agreement_status: str
    effective_from: str
    created_at: str
    updated_at: str
    version: int


class OperatingWeek(TypedDict, total=False):
    id: str
    restaurant_id: str
    week_start_on: str
    operating_day_count: int
    forecast_revenue_cents: int
    planned_labor_hours: int
    actual_revenue_cents: Optional[int]
    week_status: str
    created_at: str
    updated_at: str
    version: int


class Scorecard(TypedDict, total=False):
    id: str
    operator_id: str
    period_start_on: str
    period_end_on: str
    food_safety_score: int
    service_speed_score: int
    community_engagement_score: int
    composite_score: Optional[int]
    rating: Optional[str]
    scorecard_status: str
    created_at: str
    updated_at: str
    version: int


class RelocationRequest(TypedDict, total=False):
    id: str
    operator_id: str
    kind: str
    target_restaurant_id: str
    reason_text: str
    request_status: str
    votes_for: int
    votes_against: int
    created_at: str
    updated_at: str
    version: int


class ExitCase(TypedDict, total=False):
    id: str
    operator_id: str
    reason: str
    notice_given_on: str
    effective_on: str
    successor_candidate_id: Optional[str]
    final_statement_id: Optional[str]
    exit_status: str
    created_at: str
    updated_at: str
    version: int


class RevenueShareStatement(TypedDict, total=False):
    id: str
    operator_id: str
    operating_week_id: str
    gross_revenue_cents: int
    brand_fee_cents: int
    occupancy_charge_cents: int
    operator_share_cents: int
    statement_kind: str
    statement_status: str
    created_at: str
    updated_at: str
    version: int


class CommitteeVote(TypedDict, total=False):
    # Immutable ballot: carries only id + created_at (no updated_at, no version).
    id: str
    relocation_request_id: str
    committee_member_id: str
    vote: str
    cast_at: str
    created_at: str
