"""Entity serialisers.

Field lists mirror SCAFFOLD.yaml entities[] exactly.  Entities with
``common_fields: true`` expose id/created_at/updated_at/version;
NotificationDispatch and DataControlAction are append-only receipts and expose
only id and created_at from the common set (PRD 2.4).
"""
from decimal import Decimal

import store

COMMON = ("id", "created_at", "updated_at", "version")
RECEIPT_COMMON = ("id", "created_at")

FIELDS = {
    "Agency": (
        "name", "jurisdiction_code", "status", "onboarding_agreement_version",
        "reviewer_note", "status_reason", "min_device_threshold",
        "max_open_requests", "period_request_quota",
        "post_share_retention_days", "justification_min_chars",
        "open_request_count", "requests_submitted_count", "latest_report_id",
    ),
    "Officer": (
        "agency_id", "badge_number", "full_name", "duty_role",
        "requests_submitted_count", "audits_completed_count",
    ),
    "Resident": (
        "display_name", "email", "home_x_m", "home_y_m", "status",
        "data_sharing_opt_out", "alert_radius_m", "notification_budget_per_day",
        "notification_mute_enabled", "notifications_sent_today",
        "fatigue_state", "accuracy_strike_count",
        "discrimination_strike_count", "total_strike_score",
        "post_privilege_state", "lifetime_shared_footage_seconds",
        "retained_footage_seconds", "purged_footage_seconds",
    ),
    "Device": (
        "owner_resident_id", "label", "grid_x_m", "grid_y_m",
        "retention_window_days", "status", "auto_decline_requests",
        "auto_decline_source", "solicitations_received_count",
        "pending_solicitation_count",
    ),
    "RequestArea": (
        "agency_id", "created_by_officer_id", "area_label", "center_x_m",
        "center_y_m", "radius_m", "window_start_utc", "window_end_utc",
        "status", "locked_at", "effective_min_devices", "eligible_device_count",
        "derived_request_count", "invalidated_reason",
    ),
    "VideoRequest": (
        "request_area_id", "agency_id", "submitting_officer_id",
        "auditor_officer_id", "case_number", "lifecycle_state",
        "compliance_state", "justification_text", "statutory_basis",
        "justification_logged_at", "audit_note", "withdraw_reason",
        "submitted_at", "expires_at", "solicitation_count", "pending_count",
        "shared_count", "declined_count", "expired_count", "withdrawn_count",
        "shared_clip_count", "provisional_share_rate_bps",
    ),
    "ConsentSolicitation": (
        "video_request_id", "device_id", "resident_id", "status",
        "distance_sq_m2", "dispatch_rank", "respond_deadline_utc",
        "notification_suppressed", "suppression_reason", "responded_at",
        "decline_reason", "clip_count",
    ),
    "SharedClip": (
        "consent_solicitation_id", "video_request_id", "device_id",
        "owner_resident_id", "recorded_start_utc", "duration_seconds",
        "shared_at", "retention_variant", "retention_expires_at", "status",
        "purged_at", "purge_reason",
    ),
    "ResidentPost": (
        "author_resident_id", "parent_post_id", "body", "category",
        "post_x_m", "post_y_m", "alert_fanout_cap",
        "protected_class_term_count", "unverified_assertion_count",
        "location_profiling_count", "hostile_tone_count",
        "discrimination_score", "state", "flag_count",
        "flagged_by_resident_ids", "revision_count", "alert_candidate_count",
        "alert_fanout_count", "alert_suppressed_count", "auto_flag_reason",
    ),
    "ModerationCase": (
        "resident_post_id", "opened_reason", "opened_by_user_id",
        "decided_by_user_id", "state", "decision", "decision_note",
        "decided_at", "superseded_by_case_created_at",
        "post_discrimination_score_at_open",
    ),
    "NotificationDispatch": (
        "resident_id", "kind", "source_ref_id", "batch_sequence_no",
        "suppressed", "suppression_reason", "recipient_budget_snapshot",
        "recipient_effective_budget", "dispatched_at",
    ),
    "TransparencyReport": (
        "agency_id", "period_start_utc", "period_end_utc", "variant",
        "compiled_by_user_id", "requests_submitted_count",
        "solicitations_dispatched_count", "suppressed_dispatch_count",
        "shared_count", "declined_count", "expired_count", "withdrawn_count",
        "pending_count", "opt_out_excluded_count", "purged_clip_count",
        "provisional_share_rate_bps", "certified_share_rate_bps",
        "published_share_rate_bps", "certification_note", "certified_at",
        "certified_by_user_id",
    ),
    "DataControlAction": (
        "resident_id", "action_type", "reason", "affected_device_count",
        "affected_solicitation_count", "affected_clip_count",
        "affected_request_count", "applied_at",
    ),
}

RECEIPTS = ("NotificationDispatch", "DataControlAction")


def _value(value):
    if hasattr(value, "tzinfo"):
        return store.fmt_ts(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, list):
        return list(value)
    return value


def dump(kind, row):
    if row is None:
        return None
    common = RECEIPT_COMMON if kind in RECEIPTS else COMMON
    out = {}
    for key in common:
        out[key] = _value(row.get(key))
    for key in FIELDS[kind]:
        out[key] = _value(row.get(key))
    return out


def dump_all(kind, rows):
    return [dump(kind, r) for r in rows]
