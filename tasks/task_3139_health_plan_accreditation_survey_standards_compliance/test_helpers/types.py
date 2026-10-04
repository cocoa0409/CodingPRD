"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PLAN_COORDINATOR = "PlanCoordinator"
    ACCREDITATION_OFFICER = "AccreditationOfficer"
    SURVEYOR = "Surveyor"
    PUBLIC_VIEWER = "PublicViewer"


class HealthPlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EditionStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    EVIDENCE_REVIEW = "EVIDENCE_REVIEW"
    SURVEY_SCHEDULING = "SURVEY_SCHEDULING"
    SURVEY_IN_PROGRESS = "SURVEY_IN_PROGRESS"
    SCORING = "SCORING"
    DECIDED = "DECIDED"
    CORRECTIVE_ACTION = "CORRECTIVE_ACTION"
    RESURVEY_IN_PROGRESS = "RESURVEY_IN_PROGRESS"
    WITHDRAWN = "WITHDRAWN"
    CLOSED = "CLOSED"


class EvidenceStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class SampleStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    SCORED = "SCORED"


class SurveyStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class QuestionStatus(str, Enum):
    LOGGED = "LOGGED"
    ADJUDICATED = "ADJUDICATED"


class ScoreStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"
    VOIDED = "VOIDED"


class CapStatus(str, Enum):
    OPEN = "OPEN"
    EVIDENCE_SUBMITTED = "EVIDENCE_SUBMITTED"
    VERIFIED = "VERIFIED"


class OutcomeStatus(str, Enum):
    ACCREDITED = "ACCREDITED"
    ACCREDITED_WITH_CAP = "ACCREDITED_WITH_CAP"
    PROVISIONAL = "PROVISIONAL"
    DENIED = "DENIED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    LATE = "LATE"
    ACCEPTED = "ACCEPTED"
    RETURNED = "RETURNED"


class ProductLine(str, Enum):
    COMMERCIAL = "COMMERCIAL"
    MEDICARE = "MEDICARE"
    MEDICAID = "MEDICAID"
    MARKETPLACE = "MARKETPLACE"


class ElementCategory(str, Enum):
    UM = "UM"
    CR = "CR"
    MRR = "MRR"
    QI = "QI"


class SampleType(str, Enum):
    DENIAL = "DENIAL"
    APPEAL = "APPEAL"
    CREDENTIALING = "CREDENTIALING"


class TimelinessBasis(str, Enum):
    DECISION_DATE = "DECISION_DATE"
    RESOLUTION_DATE = "RESOLUTION_DATE"


class SurveyType(str, Enum):
    FULL = "FULL"
    RESURVEY = "RESURVEY"


class SurveyMode(str, Enum):
    VIRTUAL = "VIRTUAL"
    ONSITE = "ONSITE"
    HYBRID = "HYBRID"


class CredentialLevel(str, Enum):
    LEAD = "LEAD"
    STAFF = "STAFF"


class ScoringBasis(str, Enum):
    FILE_REVIEW = "FILE_REVIEW"
    RESURVEY = "RESURVEY"


class CapOrigin(str, Enum):
    AUTO = "AUTO"
    MANUAL = "MANUAL"


class HealthPlan(TypedDict, total=False):
    id: str
    name: str
    plan_code: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductLineScope(TypedDict, total=False):
    id: str
    health_plan_id: str
    product_line: str
    state_codes: List[str]
    member_count: int
    created_at: str
    updated_at: str
    version: int


class StandardsEdition(TypedDict, total=False):
    id: str
    edition_year: int
    effective_from: str
    effective_until: str
    min_file_sample_per_category: int
    timeliness_threshold: float
    status: str
    created_at: str
    updated_at: str
    version: int


class StandardElement(TypedDict, total=False):
    id: str
    standards_edition_id: str
    element_code: str
    category: str
    max_points: int
    is_must_pass: bool
    evidence_required_count: int
    created_at: str
    updated_at: str
    version: int


class AccreditationApplication(TypedDict, total=False):
    id: str
    health_plan_id: str
    product_line_scope_id: str
    standards_edition_id: str
    review_period_start: str
    review_period_end: str
    status: str
    total_awarded_points: float
    total_forfeited_points: float
    created_at: str
    updated_at: str
    version: int


class EvidenceItem(TypedDict, total=False):
    id: str
    application_id: str
    standard_element_id: str
    title: str
    review_note: Optional[str]
    revision_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FileReviewSample(TypedDict, total=False):
    id: str
    application_id: str
    sample_type: str
    category: str
    required_size: int
    timeliness_basis: str
    timely_case_count: int
    timeliness_rate: Optional[float]
    must_pass_threshold_breached: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class FileReviewCase(TypedDict, total=False):
    id: str
    file_review_sample_id: str
    case_reference: str
    service_date: str
    decision_date: str
    resolution_date: str
    required_turnaround_days: int
    is_timely: bool
    days_to_basis: int
    created_at: str
    updated_at: str
    version: int


class Survey(TypedDict, total=False):
    id: str
    application_id: str
    survey_type: str
    mode: str
    start_date: str
    end_date: str
    budgeted_surveyor_hours: int
    frozen_cap_closure_rate: Optional[float]
    scheduled_minutes: int
    completed_minutes: int
    cancelled_minutes: int
    active_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SurveySession(TypedDict, total=False):
    id: str
    survey_id: str
    surveyor_id: str
    session_date: str
    start_minute: int
    end_minute: int
    is_onsite: bool
    duration_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Surveyor(TypedDict, total=False):
    id: str
    name: str
    credential_level: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class SurveyorQuestion(TypedDict, total=False):
    id: str
    survey_session_id: str
    standard_element_id: str
    question_text: str
    raises_gap: bool
    gap_confirmed: Optional[bool]
    status: str
    created_at: str
    updated_at: str
    version: int


class ElementScore(TypedDict, total=False):
    id: str
    application_id: str
    standard_element_id: str
    scoring_basis: str
    sample_rate_used: Optional[float]
    evidence_count_used: int
    gap_count_used: int
    awarded_points: float
    forfeited_points: float
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityMeasureResult(TypedDict, total=False):
    id: str
    product_line_scope_id: str
    measure_code: str
    measurement_year: int
    percentile: int
    is_reportable: bool
    created_at: str
    updated_at: str
    version: int


class ConsumerSurveyScore(TypedDict, total=False):
    id: str
    product_line_scope_id: str
    survey_year: int
    composite_score: float
    response_count: int
    created_at: str
    updated_at: str
    version: int


class CorrectiveActionPlan(TypedDict, total=False):
    id: str
    application_id: str
    standard_element_id: str
    gap_description: str
    due_date: str
    is_overdue: bool
    origin: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AccreditationOutcome(TypedDict, total=False):
    id: str
    application_id: str
    composite_score: float
    measure_bonus: float
    must_pass_failure_count: int
    status: str
    decision_sequence: int
    published: bool
    public_display_until: Optional[str]
    is_publicly_displayed: bool
    decided_at: str
    created_at: str
    updated_at: str
    version: int


class AnnualReport(TypedDict, total=False):
    id: str
    application_id: str
    reporting_year: int
    attestation: str
    due_date: str
    is_late: bool
    status: str
    created_at: str
    updated_at: str
    version: int
