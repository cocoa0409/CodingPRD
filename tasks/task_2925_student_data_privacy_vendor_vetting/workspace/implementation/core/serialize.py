"""Row serializers: one per entity, with a pinned field list.

Private bookkeeping keys (anything beginning with an underscore) never leave the
service.  Instants render as ISO 8601 UTC with three fractional digits and
decimals render as JSON numbers (PRD 2.2, 2.8).
"""
from datetime import datetime
from decimal import Decimal

from . import store

_COMMON = ("id",)
_TAIL = ("created_at", "updated_at", "version")


def _value(value):
    if isinstance(value, datetime):
        return store.fmt_dt(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return list(value)
    return value


def _make(fields):
    keys = _COMMON + tuple(fields) + _TAIL

    def serializer(row):
        return dict((key, _value(row.get(key))) for key in keys)

    return serializer


vendor = _make((
    "legal_name", "hq_country_code", "breach_notification_hours", "data_deletion_days",
    "signed_state_addendum", "subprocessor_disclosure_complete", "status", "privacy_posture",
    "risk_score", "reauthorization_risk_score", "open_incident_count",
    "flagged_subprocessor_count", "suspended_at",
))

subprocessor = _make((
    "vendor_id", "processor_vendor_id", "name", "country_code", "data_categories", "purpose",
    "sub_breach_notification_hours", "status", "reviewed_note",
))

application = _make((
    "vendor_id", "name", "category", "grade_band_low", "grade_band_high", "sso_protocol",
    "sso_verified", "accessibility_conformance_level", "vpat_on_file", "status",
    "catalog_visibility", "max_permitted_tier", "exposed_sensitivity_points",
))

teacher = _make((
    "full_name", "employee_number", "school_code", "grade_bands_taught",
    "open_request_count", "status",
))

analyst = _make((
    "full_name", "credential_level", "review_capacity_minutes", "allocated_review_minutes",
    "status",
))

request = _make((
    "application_id", "requester_teacher_id", "instructional_justification",
    "requested_data_elements", "student_count_estimate", "grade_band_low", "grade_band_high",
    "status", "revision_round", "priority_score", "priority_band", "submitted_at",
    "triage_note",
))

review = _make((
    "source_request_id", "application_id", "vendor_id", "assigned_analyst_id",
    "decided_by_analyst_id", "framework_set", "estimated_minutes", "status", "round_number",
    "open_findings_count", "unresolved_findings_count", "provisional_compliance_score",
    "final_compliance_score", "remediation_due_at", "decision_note",
))

commitment = _make((
    "review_id", "element_code", "sensitivity_tier", "justified_purpose", "retention_days",
    "deletion_method", "is_minimized", "element_points", "status",
    "superseded_by_commitment_id", "decided_by_analyst_id",
))

catalog_entry = _make((
    "application_id", "review_id", "predecessor_entry_id", "effective_from", "expires_at",
    "authorized_grade_band_low", "authorized_grade_band_high", "reauthorization_due_at",
    "published_review_score", "status", "revoked_reason", "hold_restored_from",
))

detection = _make((
    "observed_domain", "application_id", "matched_catalog_entry_id", "school_code", "source",
    "observed_at", "distinct_user_count", "session_count", "classification", "exposure_score",
    "status", "triaged_by_user_id", "linked_incident_id",
))

incident = _make((
    "vendor_id", "incident_type", "detected_at", "reported_at", "contained_at",
    "affected_student_count", "max_data_tier", "severity", "notification_due_at",
    "notification_sent_at", "response_status", "notification_status", "notified_party_count",
    "remediation_note",
))
