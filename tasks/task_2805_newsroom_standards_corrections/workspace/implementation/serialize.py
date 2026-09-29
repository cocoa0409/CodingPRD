"""Resource representations.

TrainingRecord and StandardsAuditEvent are append-only and therefore carry only
`id` and `created_at` on top of their own fields -- no `updated_at`, no
`version` (PRD 2.4).
"""

from datetime import datetime
from decimal import Decimal

from store import fmt_ts

COMMON = ["created_at", "updated_at", "version"]

NEWSROOM_FIELDS = [
    "id", "name", "correction_response_sla_hours", "high_severity_open_threshold",
    "required_module_codes", "standards_posture", "open_high_severity_count",
    "training_compliance_index",
] + COMMON

JOURNALIST_FIELDS = [
    "id", "newsroom_id", "full_name", "email", "role_title", "employment_status",
    "penalty_points", "completed_required_module_count", "training_current",
    "restricted_beats",
] + COMMON

REVIEWER_FIELDS = [
    "id", "newsroom_id", "full_name", "discipline", "weekly_capacity_minutes",
    "reserved_minutes", "available_minutes",
] + COMMON

STORY_FIELDS = [
    "id", "newsroom_id", "lead_journalist_id", "headline", "defamation_claim_count",
    "privacy_subject_count", "unverified_document_count", "publication_status",
    "standards_status", "risk_index_estimate", "risk_index_actual", "risk_tier",
    "approved_anonymous_source_count", "revoked_anonymous_source_count",
    "severe_correction_count", "open_correction_request_count", "published_at",
    "unpublished_at", "editors_note_text",
] + COMMON

SOURCE_APPROVAL_FIELDS = [
    "id", "story_id", "source_alias", "source_category", "harm_risk",
    "identity_known_to_editor", "corroboration_count", "justification_text",
    "documentation_complete", "status", "decided_by_user_id", "decided_at",
    "revocation_reason",
] + COMMON

REVIEW_FIELDS = [
    "id", "story_id", "high_risk_declared", "submission_note", "requires_legal_review",
    "review_round", "status", "legal_verdict", "standards_verdict",
    "defamation_findings", "privacy_findings", "cleared_at",
] + COMMON

ASSIGNMENT_FIELDS = [
    "id", "review_id", "reviewer_id", "starts_at", "ends_at", "duration_minutes",
    "status", "cancellation_reason",
] + COMMON

CORRECTION_FIELDS = [
    "id", "story_id", "submitter_type", "submitter_email", "claim_text",
    "claimed_error_category", "reader_reported_reach", "subject_named",
    "provisional_severity_score", "provisional_severity_band",
    "adjudicated_error_category", "verified_reach", "adjudicated_severity_score",
    "adjudicated_severity_band", "outcome_type", "placement", "notice_text",
    "notice_published_at", "response_due_at", "breach_flag", "status", "resolved_at",
] + COMMON

INVESTIGATION_FIELDS = [
    "id", "journalist_id", "story_id", "allegation_type", "severity",
    "allegation_summary", "status", "penalty_points", "prior_sustained_count",
    "disclosure_obligation", "opened_by_user_id", "decided_by_user_id", "opened_at",
    "decided_at", "appeal_outcome",
] + COMMON

DISCLOSURE_FIELDS = [
    "id", "journalist_id", "disclosure_type", "subject_entity_name", "description",
    "status", "restricted_beats", "reviewed_by_user_id", "reviewed_at",
] + COMMON

ACTIVITY_FIELDS = [
    "id", "journalist_id", "activity_type", "compensated", "starts_on", "ends_on",
    "related_beat", "host_organization", "status", "decided_by_user_id", "decided_at",
    "revocation_reason",
] + COMMON

TRAINING_FIELDS = [
    "id", "journalist_id", "module_code", "case_study_reference", "completed_at",
    "created_at",
]

AUDIT_FIELDS = [
    "id", "newsroom_id", "event_type", "subject_type", "subject_id", "actor_role",
    "actor_user_id", "summary", "occurred_at", "created_at",
]


def _value(v):
    if isinstance(v, datetime):
        return fmt_ts(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, list):
        return list(v)
    return v


def _project(rec, fields):
    return dict((f, _value(rec.get(f))) for f in fields)


def newsroom_out(rec):
    return _project(rec, NEWSROOM_FIELDS)


def journalist_out(rec):
    return _project(rec, JOURNALIST_FIELDS)


def reviewer_out(rec):
    return _project(rec, REVIEWER_FIELDS)


def story_out(rec):
    return _project(rec, STORY_FIELDS)


def source_approval_out(rec):
    return _project(rec, SOURCE_APPROVAL_FIELDS)


def review_out(rec):
    return _project(rec, REVIEW_FIELDS)


def assignment_out(rec):
    return _project(rec, ASSIGNMENT_FIELDS)


def correction_out(rec):
    from calc import breach_flag
    out = _project(rec, CORRECTION_FIELDS)
    out["breach_flag"] = breach_flag(rec)
    return out


def investigation_out(rec):
    return _project(rec, INVESTIGATION_FIELDS)


def disclosure_out(rec):
    return _project(rec, DISCLOSURE_FIELDS)


def activity_out(rec):
    return _project(rec, ACTIVITY_FIELDS)


def training_out(rec):
    return _project(rec, TRAINING_FIELDS)


def audit_out(rec):
    return _project(rec, AUDIT_FIELDS)
