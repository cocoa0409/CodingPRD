"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Any, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    INSTITUTIONAL_ADMIN = "InstitutionalAdmin"
    INSTRUCTOR = "Instructor"
    STUDENT = "Student"


class ResidencyRegion(str, Enum):
    EU = "EU"
    US = "US"
    APAC = "APAC"


class RepositoryParticipation(str, Enum):
    GLOBAL_SHARED = "GLOBAL_SHARED"
    INSTITUTION_ONLY = "INSTITUTION_ONLY"
    OPT_OUT = "OPT_OUT"


class IntegrationStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class ConsentEnforcement(str, Enum):
    STRICT = "STRICT"
    LENIENT = "LENIENT"


class ConsentStatus(str, Enum):
    NOT_GIVEN = "NOT_GIVEN"
    GRANTED = "GRANTED"
    WITHDRAWN = "WITHDRAWN"


class ConsentAction(str, Enum):
    GRANT = "GRANT"
    WITHDRAW = "WITHDRAW"


class AcceptingState(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ReportVisibility(str, Enum):
    HIDDEN = "HIDDEN"
    RELEASED = "RELEASED"


class RepositoryOption(str, Enum):
    STORE_AND_COMPARE = "STORE_AND_COMPARE"
    COMPARE_ONLY = "COMPARE_ONLY"


class PipelineState(str, Enum):
    RECEIVED = "RECEIVED"
    PROCESSING = "PROCESSING"
    REPORT_READY = "REPORT_READY"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class SourceType(str, Enum):
    INTERNET = "INTERNET"
    PUBLICATION = "PUBLICATION"
    STUDENT_REPOSITORY = "STUDENT_REPOSITORY"


class SourceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETRACTED = "RETRACTED"


class MatchCategory(str, Enum):
    DIRECT_QUOTE = "DIRECT_QUOTE"
    PARAPHRASE = "PARAPHRASE"
    BIBLIOGRAPHY_ENTRY = "BIBLIOGRAPHY_ENTRY"
    BOILERPLATE = "BOILERPLATE"


class ReportState(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    STALE = "STALE"


class InstructorInterpretation(str, Enum):
    NOT_MISCONDUCT = "NOT_MISCONDUCT"
    POSSIBLE_MISCONDUCT = "POSSIBLE_MISCONDUCT"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class AssessmentState(str, Enum):
    PENDING = "PENDING"
    COMPLETE = "COMPLETE"
    SUPPRESSED = "SUPPRESSED"


class ConfidenceBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class DepositScope(str, Enum):
    GLOBAL_SHARED = "GLOBAL_SHARED"
    INSTITUTION_ONLY = "INSTITUTION_ONLY"


class DepositState(str, Enum):
    STORED = "STORED"
    QUARANTINED = "QUARANTINED"
    WITHDRAWN = "WITHDRAWN"


class AppliesTo(str, Enum):
    SUBMISSIONS = "SUBMISSIONS"
    REPORTS = "REPORTS"
    BOTH = "BOTH"


class PolicyState(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class GradeState(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    RELEASED = "RELEASED"


class Institution(TypedDict, total=False):
    id: str
    name: str
    residency_region: str
    repository_participation: str
    cross_institution_comparison_enabled: bool
    ai_detection_enabled: bool
    data_residency_locked: bool
    comparable_submission_count: int
    created_at: str
    updated_at: str
    version: int


class LmsIntegration(TypedDict, total=False):
    id: str
    institution_id: str
    provider: str
    external_key: str
    status: str
    consent_enforcement: str
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict, total=False):
    id: str
    institution_id: str
    email: str
    full_name: str
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict, total=False):
    id: str
    institution_id: str
    external_lms_id: str
    email: str
    full_name: str
    home_region: str
    consent_status: str
    consent_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Assignment(TypedDict, total=False):
    id: str
    lms_integration_id: str
    instructor_id: str
    title: str
    due_at: str
    accepting_state: str
    report_visibility: str
    repository_option: str
    exclude_quotes: bool
    exclude_bibliography: bool
    exclude_small_matches: bool
    small_match_threshold_words: int
    max_submissions_per_student: int
    submission_count: int
    created_at: str
    updated_at: str
    version: int


class Submission(TypedDict, total=False):
    id: str
    assignment_id: str
    student_id: str
    content_text: str
    word_count: int
    pipeline_state: str
    revision_number: int
    supersedes_submission_id: Optional[str]
    submitted_at: str
    ai_burstiness: Optional[float]
    ai_perplexity: Optional[float]
    ai_stylometry: Optional[float]
    created_at: str
    updated_at: str
    version: int


class SourceDocument(TypedDict, total=False):
    id: str
    origin_institution_id: str
    source_type: str
    uri: str
    region: str
    publication_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MatchFragment(TypedDict, total=False):
    """Append-only record (PRD §2.4): carries ONLY id and created_at — no
    updated_at, no version."""
    id: str
    created_at: str
    submission_id: str
    source_document_id: str
    matched_word_count: int
    match_category: str
    offset_start: int
    weighted_words: int
    excluded: bool


class SimilarityReport(TypedDict, total=False):
    id: str
    submission_id: str
    raw_score_bps: int
    filtered_score_bps: int
    exclusion_snapshot: dict
    report_state: str
    instructor_interpretation: Optional[str]
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AiWritingAssessment(TypedDict, total=False):
    id: str
    submission_id: str
    ai_score_bps: Optional[int]
    confidence_band: Optional[str]
    conservative_score_bps: Optional[int]
    assessment_state: str
    created_at: str
    updated_at: str
    version: int


class RepositoryDeposit(TypedDict, total=False):
    id: str
    submission_id: str
    institution_id: str
    scope: str
    deposit_state: str
    stored_at: str
    created_at: str
    updated_at: str
    version: int


class DataRetentionPolicy(TypedDict, total=False):
    id: str
    institution_id: str
    region: str
    applies_to: str
    retention_start: str
    retention_end: str
    policy_state: str
    created_at: str
    updated_at: str
    version: int


class GradeEntry(TypedDict, total=False):
    id: str
    submission_id: str
    score_points: float
    feedback_text: str
    grade_state: str
    pinned_report_version: int
    created_at: str
    updated_at: str
    version: int
