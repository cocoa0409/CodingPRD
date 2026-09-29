"""Entity assertions and domain invariant checkers for the LMS API."""
import pytest

from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)

from .types import (
    TermLifecycleState, ContinuityPosture, RetentionClass, PrimaryAffiliation,
    ShellType, ProvisioningState, EnrollmentRole, EnrollmentState, BatchState,
    MergeState, ItemType, CopyState, JobState, DateShiftMode, DataSharingScope,
    WcagLevel, ReviewDimensionState, ApprovalState, ReviewDimension,
    ReviewDecision, PlacementState, PassbackState, GradeVariant, DisputeState,
    WindowKind, WindowState,
)

_MEMBERS = lambda enum_cls: [m.value for m in enum_cls]


# ─── Common record properties (PRD §2.4) ──────────────────────────────────

def assert_common_fields(data: dict, entity: str = "record"):
    """id + created_at + updated_at + version, for every record but ToolReview."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp with three "
        f"fractional digits, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity}.updated_at must be an ISO 8601 UTC timestamp, got "
        f"{data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), f"{entity}.version must be an integer"
    assert data["version"] >= 1, f"{entity}.version starts at 1"


def assert_append_only_fields(data: dict, entity: str = "record"):
    """id + created_at only — no updated_at and no version."""
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be an ISO 8601 UTC timestamp"
    )
    assert "updated_at" not in data, (
        f"{entity} is immutable: updated_at must be absent from the response"
    )
    assert "version" not in data, (
        f"{entity} is immutable: version must be absent from the response"
    )


def assert_two_decimals(value, field: str):
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{field} must be a JSON number, got {value!r}"
    )
    assert_cost_precision(float(value))


# ─── Per-entity assertions ────────────────────────────────────────────────

def assert_academic_term(data: dict):
    assert_common_fields(data, "AcademicTerm")
    assert isinstance(data["term_code"], str) and data["term_code"]
    assert data["lifecycle_state"] in _MEMBERS(TermLifecycleState)
    assert data["continuity_posture"] in _MEMBERS(ContinuityPosture)
    assert data["retention_class"] in _MEMBERS(RetentionClass)
    for f in ("term_start_at", "term_end_at", "add_drop_deadline_at",
              "finals_window_start_at", "finals_window_end_at",
              "student_access_end_at"):
        assert is_iso8601_timestamp(data[f]), f"AcademicTerm.{f} must be ISO 8601"
    if data.get("retention_purge_at") is not None:
        assert is_iso8601_timestamp(data["retention_purge_at"])
    assert isinstance(data["access_grace_days"], int)
    assert 0 <= data["access_grace_days"] <= 365
    assert_two_decimals(data["rollover_completion_pct"], "rollover_completion_pct")
    for f in ("published_shell_count", "overflow_shell_count",
              "total_active_enrollments", "open_amendment_count", "sis_sync_epoch"):
        assert isinstance(data[f], int), f"AcademicTerm.{f} must be an integer"
        assert data[f] >= 0, f"AcademicTerm.{f} must not go negative"


def assert_person(data: dict):
    assert_common_fields(data, "Person")
    assert isinstance(data["sis_person_id"], str) and data["sis_person_id"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["primary_affiliation"] in _MEMBERS(PrimaryAffiliation)
    assert isinstance(data["ferpa_block"], bool)
    if data.get("access_revoked_at") is not None:
        assert is_iso8601_timestamp(data["access_revoked_at"])
    assert_two_decimals(data["sandbox_storage_charge_usd"], "sandbox_storage_charge_usd")
    assert data["sandbox_storage_charge_usd"] >= 0


def assert_course_shell(data: dict):
    assert_common_fields(data, "CourseShell")
    assert is_valid_uuid(data["term_id"])
    assert is_valid_uuid(data["owner_person_id"])
    assert isinstance(data["sis_section_code"], str) and data["sis_section_code"]
    assert data["shell_type"] in _MEMBERS(ShellType)
    assert data["provisioning_state"] in _MEMBERS(ProvisioningState)
    for f in ("base_seat_cap", "effective_seat_cap", "active_enrollment_count",
              "waitlisted_enrollment_count", "absorbed_child_count",
              "content_item_count", "blocked_placement_count"):
        assert isinstance(data[f], int), f"CourseShell.{f} must be an integer"
        assert data[f] >= 0, f"CourseShell.{f} must not go negative"
    assert_two_decimals(data["seat_utilization_pct"], "seat_utilization_pct")
    assert_two_decimals(data["storage_mb"], "storage_mb")
    assert_two_decimals(data["total_points_possible"], "total_points_possible")
    assert isinstance(data["overflow_flag"], bool)
    assert isinstance(data["publish_readiness"], bool)
    if data.get("sandbox_expires_at") is not None:
        assert is_iso8601_timestamp(data["sandbox_expires_at"])


def assert_enrollment(data: dict):
    assert_common_fields(data, "Enrollment")
    assert is_valid_uuid(data["shell_id"])
    assert is_valid_uuid(data["person_id"])
    assert data["role"] in _MEMBERS(EnrollmentRole)
    assert data["enrollment_state"] in _MEMBERS(EnrollmentState)
    if data["enrollment_state"] == EnrollmentState.WAITLISTED.value:
        assert isinstance(data["waitlist_position"], int) and data["waitlist_position"] >= 1
    else:
        assert data.get("waitlist_position") is None, (
            "waitlist_position is null unless the row is WAITLISTED"
        )
    for f in ("earned_points_total", "graded_points_possible",
              "provisional_grade_pct", "disputed_points_held"):
        assert_two_decimals(data[f], f"Enrollment.{f}")
    if data.get("final_grade_pct") is not None:
        assert_two_decimals(data["final_grade_pct"], "Enrollment.final_grade_pct")
    assert isinstance(data["reinstatement_count"], int)
    if data.get("dropped_at") is not None:
        assert is_iso8601_timestamp(data["dropped_at"])


def assert_sync_batch(data: dict):
    assert_common_fields(data, "EnrollmentSyncBatch")
    assert is_valid_uuid(data["term_id"])
    assert isinstance(data["batch_seq"], int)
    assert isinstance(data["operations"], list) and 1 <= len(data["operations"]) <= 200
    assert data["batch_state"] in _MEMBERS(BatchState)
    for f in ("validated_operation_count", "rejected_operation_count",
              "applied_add_count", "applied_drop_count",
              "promoted_from_waitlist_count"):
        assert isinstance(data[f], int) and data[f] >= 0


def assert_merge_request(data: dict):
    assert_common_fields(data, "MergeRequest")
    assert is_valid_uuid(data["parent_shell_id"])
    assert is_valid_uuid(data["child_shell_id"])
    assert data["parent_shell_id"] != data["child_shell_id"]
    assert data["merge_state"] in _MEMBERS(MergeState)
    assert isinstance(data["justification"], str)
    assert isinstance(data["submitted_by_user_id"], str) and data["submitted_by_user_id"]
    for f in ("moved_enrollment_count", "reversed_enrollment_count"):
        assert isinstance(data[f], int) and data[f] >= 0


def assert_content_item(data: dict):
    assert_common_fields(data, "ContentItem")
    assert is_valid_uuid(data["shell_id"])
    assert data["item_type"] in _MEMBERS(ItemType)
    assert isinstance(data["title"], str) and data["title"]
    assert data["copy_state"] in _MEMBERS(CopyState)
    assert isinstance(data["has_submissions"], bool)
    assert isinstance(data["date_stripped"], bool)
    assert isinstance(data["submission_count"], int) and data["submission_count"] >= 0
    assert_two_decimals(data["points_possible"], "ContentItem.points_possible")
    assert_two_decimals(data["storage_mb"], "ContentItem.storage_mb")
    if data.get("due_at") is not None:
        assert is_iso8601_timestamp(data["due_at"])
    if data["item_type"] in (ItemType.PAGE.value, ItemType.FILE.value):
        assert data["points_possible"] == 0, (
            "PAGE and FILE items carry points_possible 0.00"
        )


def assert_rollover_job(data: dict):
    assert_common_fields(data, "RolloverJob")
    for f in ("source_shell_id", "target_shell_id", "target_term_id"):
        assert is_valid_uuid(data[f])
    assert data["job_state"] in _MEMBERS(JobState)
    assert data["date_shift_mode"] in _MEMBERS(DateShiftMode)
    for f in ("strip_dates", "strip_submissions", "strip_grades"):
        assert isinstance(data[f], bool)
    for f in ("eligible_item_count", "copied_item_count", "skipped_item_count",
              "date_stripped_count", "date_shifted_count"):
        assert isinstance(data[f], int) and data[f] >= 0
    assert_two_decimals(data["copied_storage_mb"], "RolloverJob.copied_storage_mb")


def assert_tool_integration(data: dict):
    assert_common_fields(data, "ToolIntegration")
    assert isinstance(data["vendor_name"], str) and data["vendor_name"]
    assert isinstance(data["tool_name"], str) and data["tool_name"]
    assert isinstance(data["tool_version"], str) and data["tool_version"]
    assert data["data_sharing_scope"] in _MEMBERS(DataSharingScope)
    assert data["wcag_level"] in _MEMBERS(WcagLevel)
    assert isinstance(data["pii_tier"], int) and 0 <= data["pii_tier"] <= 3
    assert_two_decimals(data["vpat_score"], "ToolIntegration.vpat_score")
    assert 0 <= data["vpat_score"] <= 100
    assert data["privacy_review_state"] in _MEMBERS(ReviewDimensionState)
    assert data["accessibility_review_state"] in _MEMBERS(ReviewDimensionState)
    assert data["approval_state"] in _MEMBERS(ApprovalState)
    assert isinstance(data["active_placement_count"], int)
    if data.get("risk_score") is not None:
        assert_two_decimals(data["risk_score"], "ToolIntegration.risk_score")
        assert 0.00 <= data["risk_score"] <= 100.00, (
            "risk_score is clamped into the range from 0.00 to 100.00"
        )


def assert_tool_review(data: dict):
    assert_append_only_fields(data, "ToolReview")
    assert is_valid_uuid(data["tool_id"])
    assert data["dimension"] in _MEMBERS(ReviewDimension)
    assert data["decision"] in _MEMBERS(ReviewDecision)
    assert isinstance(data["reviewer_user_id"], str) and data["reviewer_user_id"]


def assert_tool_placement(data: dict):
    assert_common_fields(data, "ToolPlacement")
    assert is_valid_uuid(data["tool_id"])
    assert is_valid_uuid(data["shell_id"])
    assert data["placement_state"] in _MEMBERS(PlacementState)


def assert_grade_passback(data: dict):
    assert_common_fields(data, "GradePassback")
    assert is_valid_uuid(data["shell_id"])
    assert is_valid_uuid(data["term_id"])
    assert data["passback_state"] in _MEMBERS(PassbackState)
    assert data["variant_applied"] in _MEMBERS(GradeVariant)
    for f in ("submitted_points_total", "accepted_points_total",
              "disputed_points_held"):
        assert_two_decimals(data[f], f"GradePassback.{f}")
    for f in ("staged_enrollment_count", "open_dispute_count", "amendment_round"):
        assert isinstance(data[f], int) and data[f] >= 0


def assert_grade_dispute(data: dict):
    assert_common_fields(data, "GradeDispute")
    for f in ("passback_id", "enrollment_id", "content_item_id"):
        assert is_valid_uuid(data[f])
    assert data["dispute_state"] in _MEMBERS(DisputeState)
    assert_two_decimals(data["claimed_earned_points"], "claimed_earned_points")
    assert_two_decimals(data["held_points"], "held_points")
    if data.get("adjusted_earned_points") is not None:
        assert_two_decimals(data["adjusted_earned_points"], "adjusted_earned_points")
    assert isinstance(data["filed_by_user_id"], str) and data["filed_by_user_id"]
    if data.get("resolved_at") is not None:
        assert is_iso8601_timestamp(data["resolved_at"])


def assert_continuity_window(data: dict):
    assert_common_fields(data, "ContinuityWindow")
    assert is_valid_uuid(data["term_id"])
    assert data["kind"] in _MEMBERS(WindowKind)
    assert data["window_state"] in _MEMBERS(WindowState)
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert data["window_end"] > data["window_start"], (
        "window_end must be strictly after window_start"
    )
    for f in ("affected_enrollment_count", "extension_days_granted"):
        assert isinstance(data[f], int) and data[f] >= 0
    if data.get("closed_at") is not None:
        assert is_iso8601_timestamp(data["closed_at"])


# ─── Named invariants (PRD §2.8) ──────────────────────────────────────────

def assert_term_seat_ledger(term: dict, shells: list):
    """A term's total_active_enrollments equals the sum of active_enrollment_count
    across that term's shells whose provisioning_state is neither REJECTED nor
    PURGED."""
    contributing = [
        s for s in shells
        if s["provisioning_state"] not in (
            ProvisioningState.REJECTED.value, ProvisioningState.PURGED.value
        )
    ]
    expected = sum(s["active_enrollment_count"] for s in contributing)
    assert term["total_active_enrollments"] == expected, (
        f"term seat ledger drifted: total_active_enrollments="
        f"{term['total_active_enrollments']} but the contributing shells sum to "
        f"{expected}"
    )


def assert_passback_ledger(passback: dict):
    """accepted_points_total + disputed_points_held == submitted_points_total.

    Each bucket stores an already-rounded two-decimal value, so the identity is
    exact rather than approximate.
    """
    lhs = round(passback["accepted_points_total"] + passback["disputed_points_held"], 2)
    rhs = round(passback["submitted_points_total"], 2)
    assert lhs == rhs, (
        f"passback points ledger drifted: accepted {passback['accepted_points_total']} "
        f"+ disputed {passback['disputed_points_held']} != submitted "
        f"{passback['submitted_points_total']}"
    )


def assert_seat_observables(shell: dict):
    """seat_utilization_pct is active_enrollment_count over base_seat_cap, and
    overflow_flag is true exactly when active_enrollment_count exceeds
    base_seat_cap."""
    base = shell["base_seat_cap"]
    active = shell["active_enrollment_count"]
    expected_pct = round(active / base * 100 + 1e-9, 2) if base else 0.00
    assert shell["seat_utilization_pct"] == pytest.approx(expected_pct, abs=0.005), (
        f"seat_utilization_pct should be {expected_pct} "
        f"({active} active over base_seat_cap {base}), got "
        f"{shell['seat_utilization_pct']}"
    )
    assert shell["overflow_flag"] is (active > base), (
        f"overflow_flag should be {active > base} for {active} active against "
        f"base_seat_cap {base}"
    )
