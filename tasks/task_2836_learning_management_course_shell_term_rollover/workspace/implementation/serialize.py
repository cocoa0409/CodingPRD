"""Explicit output projections per entity (SCAFFOLD entity field lists).

Internal bookkeeping keys (those starting with an underscore) never leave the
service.  ToolReview omits updated_at and version entirely (PRD 2.4).
"""

COMMON_TAIL = ("created_at", "updated_at", "version")

TERM_FIELDS = (
    "id", "term_code", "lifecycle_state", "continuity_posture", "term_start_at",
    "term_end_at", "add_drop_deadline_at", "finals_window_start_at",
    "finals_window_end_at", "access_grace_days", "retention_class",
    "student_access_end_at", "retention_purge_at", "rollover_completion_pct",
    "published_shell_count", "overflow_shell_count", "total_active_enrollments",
    "open_amendment_count", "sis_sync_epoch",
) + COMMON_TAIL

PERSON_FIELDS = (
    "id", "sis_person_id", "full_name", "primary_affiliation", "ferpa_block",
    "access_revoked_at", "sandbox_storage_charge_usd",
) + COMMON_TAIL

SHELL_FIELDS = (
    "id", "term_id", "owner_person_id", "sis_section_code", "shell_type",
    "provisioning_state", "base_seat_cap", "effective_seat_cap",
    "active_enrollment_count", "waitlisted_enrollment_count",
    "seat_utilization_pct", "overflow_flag", "storage_mb",
    "merged_into_shell_id", "absorbed_child_count", "content_item_count",
    "total_points_possible", "blocked_placement_count", "publish_readiness",
    "sandbox_expires_at", "reject_reason", "unpublish_reason",
) + COMMON_TAIL

ENROLLMENT_FIELDS = (
    "id", "shell_id", "person_id", "batch_id", "merged_from_shell_id", "role",
    "enrollment_state", "waitlist_position", "earned_points_total",
    "graded_points_possible", "provisional_grade_pct", "final_grade_pct",
    "dropped_at", "reinstatement_count", "disputed_points_held",
) + COMMON_TAIL

BATCH_FIELDS = (
    "id", "term_id", "batch_seq", "operations", "batch_state",
    "validated_operation_count", "rejected_operation_count",
    "applied_add_count", "applied_drop_count", "promoted_from_waitlist_count",
    "failure_reason",
) + COMMON_TAIL

MERGE_FIELDS = (
    "id", "parent_shell_id", "child_shell_id", "justification",
    "submitted_by_user_id", "decided_by_user_id", "merge_state",
    "moved_enrollment_count", "reversed_enrollment_count",
    "seat_ledger_before", "seat_ledger_after",
) + COMMON_TAIL

ITEM_FIELDS = (
    "id", "shell_id", "source_item_id", "item_type", "title", "due_at",
    "points_possible", "storage_mb", "has_submissions", "submission_count",
    "date_stripped", "copy_state",
) + COMMON_TAIL

JOB_FIELDS = (
    "id", "source_shell_id", "target_shell_id", "target_term_id",
    "expected_target_shell_version", "strip_dates", "strip_submissions",
    "strip_grades", "date_shift_mode", "job_state", "eligible_item_count",
    "copied_item_count", "skipped_item_count", "date_stripped_count",
    "date_shifted_count", "copied_storage_mb", "failure_reason",
) + COMMON_TAIL

TOOL_FIELDS = (
    "id", "vendor_name", "tool_name", "tool_version", "data_sharing_scope",
    "pii_tier", "vpat_score", "wcag_level", "privacy_review_state",
    "accessibility_review_state", "approval_state", "risk_score",
    "approved_version", "active_placement_count", "suspension_reason",
) + COMMON_TAIL

REVIEW_FIELDS = (
    "id", "tool_id", "dimension", "decision", "reviewer_user_id",
    "conditions_note", "created_at",
)

PLACEMENT_FIELDS = (
    "id", "tool_id", "shell_id", "placement_state", "pinned_tool_version",
    "blocked_reason",
) + COMMON_TAIL

PASSBACK_FIELDS = (
    "id", "shell_id", "term_id", "passback_state", "variant_applied",
    "staged_enrollment_count", "submitted_points_total",
    "accepted_points_total", "disputed_points_held", "open_dispute_count",
    "amendment_round", "registrar_note",
) + COMMON_TAIL

DISPUTE_FIELDS = (
    "id", "passback_id", "enrollment_id", "content_item_id",
    "claimed_earned_points", "dispute_state", "held_points",
    "adjusted_earned_points", "filed_by_user_id", "resolved_at",
) + COMMON_TAIL

WINDOW_FIELDS = (
    "id", "term_id", "shell_id", "kind", "window_start", "window_end",
    "window_state", "affected_enrollment_count", "extension_days_granted",
    "closed_at",
) + COMMON_TAIL

FIELDS_BY_KIND = {
    "term": TERM_FIELDS,
    "person": PERSON_FIELDS,
    "shell": SHELL_FIELDS,
    "enrollment": ENROLLMENT_FIELDS,
    "batch": BATCH_FIELDS,
    "merge": MERGE_FIELDS,
    "item": ITEM_FIELDS,
    "job": JOB_FIELDS,
    "tool": TOOL_FIELDS,
    "review": REVIEW_FIELDS,
    "placement": PLACEMENT_FIELDS,
    "passback": PASSBACK_FIELDS,
    "dispute": DISPUTE_FIELDS,
    "window": WINDOW_FIELDS,
}


def project(record):
    fields = FIELDS_BY_KIND[record["_kind"]]
    return {name: record.get(name) for name in fields}


def project_all(records):
    return [project(record) for record in records]
