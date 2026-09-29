"""TypedDict shapes for every resource the standards-desk API returns.

Field sets follow PRD §2.4: newsrooms, journalists, reviewers, stories,
anonymous-source approvals, pre-publication reviews, review assignments,
correction requests, misconduct investigations, conflict disclosures and
outside-activity requests all carry ``id``, ``created_at``, ``updated_at``
and ``version``.  ``TrainingRecord`` and ``StandardsAuditEvent`` are
append-only and therefore carry only ``id`` and ``created_at`` — both
``updated_at`` and ``version`` are deliberately absent below.
"""

from typing import List, Optional, TypedDict


class Newsroom(TypedDict):
    id: str
    name: str
    correction_response_sla_hours: int
    high_severity_open_threshold: int
    required_module_codes: List[str]
    standards_posture: str
    open_high_severity_count: int
    training_compliance_index: float
    created_at: str
    updated_at: str
    version: int


class StandardsSummary(TypedDict):
    standards_posture: str
    open_high_severity_count: int
    training_compliance_index: float
    published_story_count: int
    open_correction_request_count: int
    breached_correction_count: int


class Journalist(TypedDict):
    id: str
    newsroom_id: str
    full_name: str
    email: str
    role_title: str
    employment_status: str
    penalty_points: int
    completed_required_module_count: int
    training_current: bool
    restricted_beats: List[str]
    created_at: str
    updated_at: str
    version: int


class Reviewer(TypedDict):
    id: str
    newsroom_id: str
    full_name: str
    discipline: str
    weekly_capacity_minutes: int
    reserved_minutes: int
    available_minutes: int
    created_at: str
    updated_at: str
    version: int


class Story(TypedDict):
    id: str
    newsroom_id: str
    lead_journalist_id: str
    headline: str
    defamation_claim_count: int
    privacy_subject_count: int
    unverified_document_count: int
    publication_status: str
    standards_status: str
    approved_anonymous_source_count: int
    revoked_anonymous_source_count: int
    severe_correction_count: int
    open_correction_request_count: int
    risk_index_estimate: float
    risk_index_actual: Optional[float]
    risk_tier: str
    published_at: Optional[str]
    unpublished_at: Optional[str]
    editors_note_text: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AnonymousSourceApproval(TypedDict):
    id: str
    story_id: str
    source_alias: str
    source_category: str
    harm_risk: str
    identity_known_to_editor: bool
    corroboration_count: int
    justification_text: Optional[str]
    documentation_complete: bool
    status: str
    decision_note: Optional[str]
    revocation_reason: Optional[str]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PrePublicationReview(TypedDict):
    id: str
    story_id: str
    status: str
    review_round: int
    requires_legal_review: bool
    high_risk_declared: bool
    submission_note: Optional[str]
    legal_verdict: Optional[str]
    standards_verdict: Optional[str]
    defamation_findings: int
    privacy_findings: int
    findings_note: Optional[str]
    cleared_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReviewAssignment(TypedDict):
    id: str
    review_id: str
    reviewer_id: str
    starts_at: str
    ends_at: str
    duration_minutes: int
    status: str
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorrectionRequest(TypedDict):
    id: str
    story_id: str
    submitter_type: str
    submitter_email: str
    claim_text: str
    claimed_error_category: str
    reader_reported_reach: int
    subject_named: bool
    status: str
    provisional_severity_score: int
    provisional_severity_band: str
    adjudicated_error_category: Optional[str]
    verified_reach: Optional[int]
    adjudicated_severity_score: Optional[int]
    adjudicated_severity_band: Optional[str]
    outcome_type: Optional[str]
    placement: Optional[str]
    notice_text: Optional[str]
    response_due_at: str
    breach_flag: bool
    outreach_channel: Optional[str]
    notice_published_at: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MisconductInvestigation(TypedDict):
    id: str
    journalist_id: str
    story_id: Optional[str]
    allegation_type: str
    severity: str
    allegation_summary: str
    status: str
    penalty_points: int
    prior_sustained_count: int
    disclosure_obligation: str
    appeal_outcome: Optional[str]
    opened_by_user_id: str
    opened_at: str
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConflictDisclosure(TypedDict):
    id: str
    journalist_id: str
    disclosure_type: str
    subject_entity_name: str
    description: str
    status: str
    restricted_beats: List[str]
    review_outcome: Optional[str]
    reviewed_by_user_id: Optional[str]
    reviewed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutsideActivityRequest(TypedDict):
    id: str
    journalist_id: str
    activity_type: str
    compensated: bool
    starts_on: str
    ends_on: str
    related_beat: str
    host_organization: str
    status: str
    decision_note: Optional[str]
    revocation_reason: Optional[str]
    decided_by_user_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TrainingRecord(TypedDict):
    """Append-only: no ``updated_at`` and no ``version`` (PRD §2.4)."""

    id: str
    journalist_id: str
    module_code: str
    case_study_reference: Optional[str]
    completed_at: str
    created_at: str


class StandardsAuditEvent(TypedDict):
    """Append-only: no ``updated_at`` and no ``version`` (PRD §2.4)."""

    id: str
    newsroom_id: str
    event_type: str
    subject_type: str
    subject_id: str
    actor_role: str
    actor_user_id: Optional[str]
    summary: str
    occurred_at: str
    created_at: str


class ClockReading(TypedDict):
    current_utc: str
