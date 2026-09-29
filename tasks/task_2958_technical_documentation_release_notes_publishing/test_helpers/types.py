"""Domain enums and entity shapes for the Docs Release Publishing API."""
from __future__ import annotations

from enum import Enum
from typing import Any, TypedDict


# ---------------------------------------------------------------------------
# Roles (§2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    DOCS_LEAD = "DocsLead"
    WRITER = "Writer"
    REVIEWER = "Reviewer"
    LOCALIZATION_COORDINATOR = "LocalizationCoordinator"
    SUPPORT_ANALYST = "SupportAnalyst"
    READER = "Reader"


ALL_ROLES = [r.value for r in UserRole]


# ---------------------------------------------------------------------------
# Release train (§3.1)
# ---------------------------------------------------------------------------

class ReleaseTrainStatus(str, Enum):
    PLANNED = "PLANNED"
    DOC_FREEZE = "DOC_FREEZE"
    GA = "GA"
    MAINTENANCE = "MAINTENANCE"
    END_OF_LIFE = "END_OF_LIFE"


RELEASE_TRAIN_SPINE = [
    ReleaseTrainStatus.PLANNED.value,
    ReleaseTrainStatus.DOC_FREEZE.value,
    ReleaseTrainStatus.GA.value,
    ReleaseTrainStatus.MAINTENANCE.value,
    ReleaseTrainStatus.END_OF_LIFE.value,
]


class DocReadinessPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


# ---------------------------------------------------------------------------
# Writer roster (§3.2)
# ---------------------------------------------------------------------------

class WriterStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"


class SeniorityTier(str, Enum):
    ASSOCIATE = "ASSOCIATE"
    SENIOR = "SENIOR"
    PRINCIPAL = "PRINCIPAL"


class ReviewerDiscipline(str, Enum):
    ENGINEERING = "ENGINEERING"
    PRODUCT = "PRODUCT"


# ---------------------------------------------------------------------------
# Plan items (§3.2)
# ---------------------------------------------------------------------------

class PlanItemStatus(str, Enum):
    DRAFTED = "DRAFTED"
    ASSIGNED = "ASSIGNED"
    IN_AUTHORING = "IN_AUTHORING"
    IN_REVIEW = "IN_REVIEW"
    IN_REVISION = "IN_REVISION"
    APPROVED_CONTENT = "APPROVED_CONTENT"
    PUBLISHED = "PUBLISHED"
    CANCELLED = "CANCELLED"


#: Plan item statuses that count toward a writer's committed load (§3.2).
WRITER_COUNTED_PLAN_ITEM_STATUSES = [
    PlanItemStatus.ASSIGNED.value,
    PlanItemStatus.IN_AUTHORING.value,
    PlanItemStatus.IN_REVIEW.value,
    PlanItemStatus.IN_REVISION.value,
    PlanItemStatus.APPROVED_CONTENT.value,
]


class IaPlacement(str, Enum):
    NEW_TOPIC = "NEW_TOPIC"
    EXISTING_TOPIC_UPDATE = "EXISTING_TOPIC_UPDATE"
    CONCEPT_HUB = "CONCEPT_HUB"


class AudienceTier(str, Enum):
    CRITICAL = "CRITICAL"
    STANDARD = "STANDARD"
    INTERNAL = "INTERNAL"


# ---------------------------------------------------------------------------
# Topics (§3.3)
# ---------------------------------------------------------------------------

class TopicReviewState(str, Enum):
    NOT_SUBMITTED = "NOT_SUBMITTED"
    PENDING_SIGNOFF = "PENDING_SIGNOFF"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    FULLY_APPROVED = "FULLY_APPROVED"


class TopicPublicationState(str, Enum):
    UNPUBLISHED = "UNPUBLISHED"
    PUBLISHED = "PUBLISHED"
    ARCHIVED = "ARCHIVED"


class HealthScoreVariant(str, Enum):
    PRE_PUBLICATION = "PRE_PUBLICATION"
    POST_PUBLICATION = "POST_PUBLICATION"


# ---------------------------------------------------------------------------
# Terminology (§3.4)
# ---------------------------------------------------------------------------

class TermStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EnforcementSeverity(str, Enum):
    BLOCKER = "BLOCKER"
    WARNING = "WARNING"


# ---------------------------------------------------------------------------
# Sign-offs (§3.5)
# ---------------------------------------------------------------------------

class SignoffState(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    SUPERSEDED = "SUPERSEDED"


class SignoffDecision(str, Enum):
    APPROVED = "APPROVED"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"


# ---------------------------------------------------------------------------
# Doc set versions (§3.6)
# ---------------------------------------------------------------------------

class DocSetVersionStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"


# ---------------------------------------------------------------------------
# Change records and release notes (§3.7)
# ---------------------------------------------------------------------------

class ChangeRecordState(str, Enum):
    SUBMITTED = "SUBMITTED"
    REWORK_REQUESTED = "REWORK_REQUESTED"
    EDITORIALLY_APPROVED = "EDITORIALLY_APPROVED"
    EXCLUDED = "EXCLUDED"
    PUBLISHED = "PUBLISHED"


class ChangeSeverity(str, Enum):
    BREAKING = "BREAKING"
    SECURITY = "SECURITY"
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    PATCH = "PATCH"


#: Severity rank ascending: heaviest weight first (§3.7).
SEVERITY_RANK_ORDER = [
    ChangeSeverity.BREAKING.value,
    ChangeSeverity.SECURITY.value,
    ChangeSeverity.MAJOR.value,
    ChangeSeverity.MINOR.value,
    ChangeSeverity.PATCH.value,
]


class ChangeCategory(str, Enum):
    FEATURE = "FEATURE"
    FIX = "FIX"
    PERFORMANCE = "PERFORMANCE"
    SECURITY_PATCH = "SECURITY_PATCH"
    DEPRECATION = "DEPRECATION"


class ReleaseNoteStatus(str, Enum):
    COMPILED = "COMPILED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


# ---------------------------------------------------------------------------
# Localization (§3.8)
# ---------------------------------------------------------------------------

class LocaleProfileStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class PublicationMode(str, Enum):
    SIMULTANEOUS = "SIMULTANEOUS"
    DELAYED = "DELAYED"


class LocalizationJobState(str, Enum):
    QUEUED = "QUEUED"
    TRANSLATED = "TRANSLATED"
    REWORK_REQUESTED = "REWORK_REQUESTED"
    SCHEDULED_DELAYED = "SCHEDULED_DELAYED"
    PUBLISHED_LOCALIZED = "PUBLISHED_LOCALIZED"
    CANCELLED = "CANCELLED"


#: Job states that hold a locale reservation open (§3.8).
LOCALIZATION_JOB_OPEN_STATES = [
    LocalizationJobState.QUEUED.value,
    LocalizationJobState.TRANSLATED.value,
    LocalizationJobState.REWORK_REQUESTED.value,
    LocalizationJobState.SCHEDULED_DELAYED.value,
]


class CostVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


#: The exact cancel_reason the archive and end-of-life cascades write (§3.6).
CASCADE_CANCEL_REASON = "CASCADE_DOC_SET_ARCHIVED"


# ---------------------------------------------------------------------------
# Deprecation notices (§3.9)
# ---------------------------------------------------------------------------

class DeprecationNoticeStatus(str, Enum):
    DRAFTED = "DRAFTED"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class SeverityTier(str, Enum):
    BREAKING = "BREAKING"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


# ---------------------------------------------------------------------------
# Reader feedback (§3.10)
# ---------------------------------------------------------------------------

class FeedbackOutcome(str, Enum):
    RESOLVED_SELF_SERVE = "RESOLVED_SELF_SERVE"
    OPENED_TICKET = "OPENED_TICKET"
    ABANDONED = "ABANDONED"


#: Outcomes that land in the deflection denominator (§3.10).
DECIDED_OUTCOMES = [
    FeedbackOutcome.RESOLVED_SELF_SERVE.value,
    FeedbackOutcome.OPENED_TICKET.value,
]


# ---------------------------------------------------------------------------
# Entity shapes (§2.4 audit fields + per-workflow fields)
# ---------------------------------------------------------------------------

class ReleaseTrain(TypedDict, total=False):
    id: str
    product_key: str
    version_label: str
    doc_freeze_date: str
    ga_date: str
    support_end_date: str
    localization_budget_cap_cents: int
    status: str
    doc_readiness_posture: str
    approved_topic_ratio: float
    plan_item_count: int
    approved_plan_item_count: int
    localization_committed_cents: int
    eol_notice_posted: bool
    created_at: str
    updated_at: str
    version: int


class Writer(TypedDict, total=False):
    id: str
    person_key: str
    full_name: str
    seniority_tier: str
    capacity_points: float
    status: str
    committed_load_points: float
    assignment_count: int
    created_at: str
    updated_at: str
    version: int


class Reviewer(TypedDict, total=False):
    id: str
    person_key: str
    full_name: str
    discipline: str
    open_signoff_count: int
    created_at: str
    updated_at: str
    version: int


class PlanItem(TypedDict, total=False):
    id: str
    release_train_id: str
    feature_key: str
    ia_placement: str
    audience_tier: str
    planned_page_count: int
    complexity_points: int
    status: str
    assigned_writer_id: str | None
    window_start_date: str | None
    window_end_date: str | None
    load_points: float
    rework_count: int
    cancel_reason: str | None
    created_at: str
    updated_at: str
    version: int


class Topic(TypedDict, total=False):
    id: str
    plan_item_id: str
    parent_topic_id: str | None
    slug: str
    title: str
    ia_depth: int
    review_state: str
    publication_state: str
    current_revision_number: int
    last_submitted_revision_number: int
    latest_body_word_count: int
    open_blocker_violations: int
    open_warning_violations: int
    health_score: float | None
    health_score_variant: str | None
    submitted_at: str | None
    approved_at: str | None
    signoff_latency_days: int | None
    published_at: str | None
    published_in_doc_set_version_id: str | None
    created_at: str
    updated_at: str
    version: int


class SourceRevision(TypedDict, total=False):
    """Append-only (§2.4): carries only ``id`` and ``created_at`` as audit fields."""
    id: str
    topic_id: str
    revision_number: int
    author_writer_id: str
    body_word_count: int
    used_terms: list[str]
    summary: str
    blocker_violation_count: int
    warning_violation_count: int
    violating_term_ids: list[str]
    created_at: str


class Signoff(TypedDict, total=False):
    id: str
    topic_id: str
    reviewer_id: str
    discipline: str
    state: str
    pinned_revision_number: int | None
    requested_at: str
    decided_at: str | None
    comment: str | None
    created_at: str
    updated_at: str
    version: int


class DocSetVersion(TypedDict, total=False):
    id: str
    release_train_id: str
    version_label: str
    status: str
    published_topic_count: int
    projected_localization_budget_cents: int
    published_at: str | None
    archived_at: str | None
    eol_notice_text: str | None
    created_at: str
    updated_at: str
    version: int


class ChangeRecord(TypedDict, total=False):
    id: str
    release_train_id: str
    internal_summary: str
    severity: str
    category: str
    affected_component: str
    state: str
    submitted_by_user_id: str
    editorial_by_user_id: str | None
    customer_facing_text: str | None
    terminology_blocker_count: int
    rework_count: int
    exclusion_reason: str | None
    created_at: str
    updated_at: str
    version: int


class ReleaseNote(TypedDict, total=False):
    id: str
    release_train_id: str
    doc_set_version_id: str
    status: str
    compiled_at: str
    published_at: str | None
    headline_severity: str
    severity_counts: dict[str, int]
    included_change_record_ids: list[str]
    coverage_factor_provisional: float | None
    impact_score_provisional: float | None
    coverage_factor_final: float | None
    impact_score_final: float | None
    created_at: str
    updated_at: str
    version: int


class LocaleProfile(TypedDict, total=False):
    id: str
    locale_code: str
    publication_mode: str
    tm_coverage_pct: float
    per_word_rate_cents: float
    sla_days: int
    parallel_job_limit: int
    status: str
    committed_source_words: int
    open_job_count: int
    created_at: str
    updated_at: str
    version: int


class LocalizationJob(TypedDict, total=False):
    id: str
    topic_id: str
    locale_profile_id: str
    window_start_date: str
    window_end_date: str
    state: str
    auto_created: bool
    source_revision_number: int
    reserved_source_words: int
    translated_word_count: int | None
    tm_matched_word_count: int | None
    leverage_pct: float
    rush_surcharge_cents: int
    volume_discount_cents: int
    estimated_cost_cents: int
    final_cost_cents: int | None
    cost_variant: str
    rework_count: int
    publication_mode_applied: str | None
    scheduled_publish_date: str | None
    published_at: str | None
    cancel_reason: str | None
    created_at: str
    updated_at: str
    version: int


class TerminologyTerm(TypedDict, total=False):
    id: str
    term: str
    preferred_form: str
    forbidden_forms: list[str]
    enforcement_severity: str
    status: str
    retired_at: str | None
    created_at: str
    updated_at: str
    version: int


class DeprecationNotice(TypedDict, total=False):
    id: str
    release_train_id: str
    feature_key: str
    severity_tier: str
    announce_date: str
    deprecated_date: str
    removal_date: str
    migration_guide_topic_id: str
    notice_days: int
    earliest_removal_date: str
    status: str
    published_at: str | None
    created_at: str
    updated_at: str
    version: int


class PageFeedback(TypedDict, total=False):
    """Append-only (§2.4): carries only ``id`` and ``created_at`` as audit fields."""
    id: str
    topic_id: str
    rating: int
    outcome: str
    locale_code: str
    session_key: str
    comment: str | None
    created_at: str


class DeflectionSummary(TypedDict, total=False):
    topic_id: str
    window_start_date: str
    window_end_date: str
    sample_count: int
    mean_rating: float | None
    deflection_pct: float | None
    ticket_rate_pct: float | None


JsonDict = dict[str, Any]
