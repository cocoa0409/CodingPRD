"""Domain types for the Teacher Evaluation & Tenure Progression API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles ────────────────────────────────────────────────────────────────

class UserRole(str, Enum):
    HR_ADMIN = "HrAdmin"
    EVALUATOR = "Evaluator"
    TEACHER = "Teacher"
    APPEAL_PANELIST = "AppealPanelist"
    UNION_REP = "UnionRep"


# ─── Status / enum vocabularies ───────────────────────────────────────────

class SchoolLevel(str, Enum):
    ELEMENTARY = "ELEMENTARY"
    MIDDLE = "MIDDLE"
    HIGH = "HIGH"


class TenureStatus(str, Enum):
    PROBATIONARY = "PROBATIONARY"
    RECOMMENDED = "RECOMMENDED"
    TENURED = "TENURED"
    DENIED = "DENIED"
    NON_RENEWED = "NON_RENEWED"


class CertificationStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"
    SUSPENDED = "SUSPENDED"


class CycleStatus(str, Enum):
    SCHEDULING = "SCHEDULING"
    SCORING = "SCORING"
    SUBMITTED = "SUBMITTED"
    FINALIZED = "FINALIZED"
    CLOSED = "CLOSED"


class DisputeState(str, Enum):
    NONE = "NONE"
    APPEALED = "APPEALED"
    APPEAL_RESOLVED = "APPEAL_RESOLVED"
    GRIEVED = "GRIEVED"
    GRIEVANCE_RESOLVED = "GRIEVANCE_RESOLVED"


class CycleType(str, Enum):
    COMPREHENSIVE = "COMPREHENSIVE"
    FOCUSED = "FOCUSED"


class CompositeRating(str, Enum):
    INEFFECTIVE = "INEFFECTIVE"
    DEVELOPING = "DEVELOPING"
    EFFECTIVE = "EFFECTIVE"
    HIGHLY_EFFECTIVE = "HIGHLY_EFFECTIVE"


class CompositeVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class ObservationStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CONDUCTED = "CONDUCTED"
    SCORED = "SCORED"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    ACCEPTED = "ACCEPTED"
    VOIDED = "VOIDED"


class ObservationType(str, Enum):
    FORMAL = "FORMAL"
    INFORMAL = "INFORMAL"


class DomainCode(str, Enum):
    PLANNING = "PLANNING"
    ENVIRONMENT = "ENVIRONMENT"
    INSTRUCTION = "INSTRUCTION"
    PROFESSIONALISM = "PROFESSIONALISM"


class ArtifactType(str, Enum):
    LESSON_PLAN = "LESSON_PLAN"
    STUDENT_WORK = "STUDENT_WORK"
    REFLECTION = "REFLECTION"
    VIDEO = "VIDEO"


class ArtifactStatus(str, Enum):
    ATTACHED = "ATTACHED"
    WITHDRAWN = "WITHDRAWN"


class SubmittedByRole(str, Enum):
    EVALUATOR = "EVALUATOR"
    TEACHER = "TEACHER"


class MeasureCode(str, Enum):
    STATE_ASSESSMENT = "STATE_ASSESSMENT"
    SLO = "SLO"
    SCHOOLWIDE = "SCHOOLWIDE"


class GrowthMeasureStatus(str, Enum):
    REPORTED = "REPORTED"
    CERTIFIED = "CERTIFIED"
    EXCLUDED = "EXCLUDED"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXTENDED = "EXTENDED"
    COMPLETED_SUCCESS = "COMPLETED_SUCCESS"
    COMPLETED_FAIL = "COMPLETED_FAIL"
    VOIDED = "VOIDED"


class PlanTriggerReason(str, Enum):
    INEFFECTIVE_RATING = "INEFFECTIVE_RATING"
    PRIOR_PLAN_FAILED = "PRIOR_PLAN_FAILED"


class AppealStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    UPHELD = "UPHELD"
    MODIFIED = "MODIFIED"
    REMANDED = "REMANDED"


class AppealGrounds(str, Enum):
    PROCEDURAL = "PROCEDURAL"
    EVIDENTIARY = "EVIDENTIARY"
    SCORING = "SCORING"


class GrievanceStatus(str, Enum):
    FILED = "FILED"
    SUSTAINED = "SUSTAINED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class GrievanceRemedy(str, Enum):
    NONE = "NONE"
    RATING_VACATED = "RATING_VACATED"
    PLAN_VOIDED = "PLAN_VOIDED"


class ArticleCode(str, Enum):
    ART_12_EVALUATION = "ART_12_EVALUATION"
    ART_14_DISCIPLINE = "ART_14_DISCIPLINE"


class CalibrationOutcome(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"


# ─── Entity shapes ────────────────────────────────────────────────────────
# Every resource kind in this system carries id, created_at, updated_at and
# version (PRD §2.4).

class EvaluationPolicy(TypedDict):
    id: str
    school_year: str
    observation_weight_pct: float
    growth_weight_pct: float
    planning_weight_pct: float
    environment_weight_pct: float
    instruction_weight_pct: float
    professionalism_weight_pct: float
    required_formal_count: int
    required_informal_count: int
    unannounced_multiplier: float
    informal_cap: float
    highly_effective_threshold: float
    effective_threshold: float
    developing_threshold: float
    evidence_min_artifacts: int
    remediation_days: int
    max_plan_extension_days: int
    appeal_window_days: int
    tenure_required_years: int
    tenure_min_consecutive_effective: int
    min_days_between_formals: int
    calibration_drift_tolerance: float
    calibration_max_consecutive_failures: int
    observation_stipend_cents: int
    created_at: str
    updated_at: str
    version: int


class School(TypedDict):
    id: str
    name: str
    code: str
    level: str
    evaluation_budget_allocated_cents: int
    evaluation_budget_committed_cents: int
    evaluation_budget_remaining_cents: int
    created_at: str
    updated_at: str
    version: int


class Educator(TypedDict):
    id: str
    school_id: str
    employee_number: str
    full_name: str
    service_start_date: str
    tenure_status: str
    completed_service_years: int
    consecutive_effective_years: int
    tenure_track_hold: bool
    last_composite_rating: Optional[str]
    tenure_recommended_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Evaluator(TypedDict):
    id: str
    full_name: str
    certification_status: str
    certification_expires_on: Optional[str]
    consecutive_failed_calibrations: int
    passed_calibration_count: int
    calibration_drift_rolling: float
    calibration_drift_anchor: float
    created_at: str
    updated_at: str
    version: int


class EvaluationCycle(TypedDict):
    id: str
    educator_id: str
    policy_id: str
    school_year: str
    cycle_type: str
    status: str
    dispute_state: str
    completed_formal_count: int
    completed_informal_count: int
    evidence_artifact_count: int
    observation_component: Optional[float]
    growth_component: Optional[float]
    evidence_adjustment: float
    composite_score: Optional[float]
    composite_rating: Optional[str]
    composite_variant: Optional[str]
    finalized_at: Optional[str]
    appeal_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Observation(TypedDict):
    id: str
    cycle_id: str
    evaluator_id: str
    observation_type: str
    announced: bool
    scheduled_start: str
    scheduled_end: str
    status: str
    scored_domain_count: int
    weighted_score: Optional[float]
    evidence_count: int
    stipend_cents: int
    return_count: int
    return_reason: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RubricScore(TypedDict):
    id: str
    observation_id: str
    domain_code: str
    raw_score: int
    weighted_contribution: float
    superseded: bool
    observation_version_after: int
    created_at: str
    updated_at: str
    version: int


class EvidenceArtifact(TypedDict):
    id: str
    observation_id: str
    artifact_type: str
    title: str
    status: str
    submitted_by_role: str
    created_at: str
    updated_at: str
    version: int


class GrowthMeasure(TypedDict):
    id: str
    cycle_id: str
    measure_code: str
    index_value: float
    coverage_pct: float
    status: str
    cycle_version_after: int
    created_at: str
    updated_at: str
    version: int


class ImprovementPlan(TypedDict):
    id: str
    cycle_id: str
    educator_id: str
    prior_plan_id: Optional[str]
    status: str
    trigger_reason: str
    started_at: str
    due_at: str
    extension_days_used: int
    escalation_level: int
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict):
    id: str
    cycle_id: str
    educator_id: str
    grounds: str
    statement: str
    status: str
    panelist_evaluator_id: Optional[str]
    adjusted_composite: Optional[float]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Grievance(TypedDict):
    id: str
    appeal_id: str
    educator_id: str
    article_code: str
    status: str
    remedy: str
    created_at: str
    updated_at: str
    version: int


class CalibrationReview(TypedDict):
    id: str
    evaluator_id: str
    anchor_lesson_code: str
    anchor_score: float
    evaluator_score: float
    deviation: float
    outcome: str
    sequence_index: Optional[int]
    created_at: str
    updated_at: str
    version: int


DOMAIN_ORDER: List[str] = [
    DomainCode.PLANNING.value,
    DomainCode.ENVIRONMENT.value,
    DomainCode.INSTRUCTION.value,
    DomainCode.PROFESSIONALISM.value,
]
