"""Payload factories — one per entity, carrying only client-supplied fields."""
import itertools

_seq = itertools.count(1)


def next_seq() -> int:
    """Monotonic counter used to keep unique-per-test values distinct."""
    return next(_seq)


DEFAULTS = {
    "TERM_START": "2026-08-24T00:00:00Z",
    "TERM_END": "2026-12-11T00:00:00Z",
    "ACCESS_GRACE_DAYS": 30,
    "RETENTION_CLASS": "STANDARD",
    "BASE_SEAT_CAP": 10,
    "FACULTY_NAME": "Ada Byron",
    "STUDENT_NAME": "Stu One",
    "ITEM_TITLE": "Midterm Project",
    "VENDOR_NAME": "Acme Analytics",
    "TOOL_NAME": "DeepProctor",
    "TOOL_VERSION": "4.2.0",
}


# ─── AcademicTerm ─────────────────────────────────────────────────────────

def create_academic_term_payload(**overrides) -> dict:
    payload = {
        "term_code": f"T{next_seq():05d}",
        "term_start_at": DEFAULTS["TERM_START"],
        "term_end_at": DEFAULTS["TERM_END"],
        "access_grace_days": DEFAULTS["ACCESS_GRACE_DAYS"],
        "retention_class": DEFAULTS["RETENTION_CLASS"],
    }
    payload.update(overrides)
    return payload


# ─── Person ───────────────────────────────────────────────────────────────

def create_person_payload(**overrides) -> dict:
    payload = {
        "sis_person_id": f"P-{next_seq():06d}",
        "full_name": DEFAULTS["FACULTY_NAME"],
        "primary_affiliation": "FACULTY",
    }
    payload.update(overrides)
    return payload


def create_student_person_payload(**overrides) -> dict:
    payload = create_person_payload(
        full_name=DEFAULTS["STUDENT_NAME"], primary_affiliation="STUDENT"
    )
    payload.update(overrides)
    return payload


# ─── CourseShell ──────────────────────────────────────────────────────────

def create_course_shell_payload(term_id, owner_person_id, **overrides) -> dict:
    payload = {
        "term_id": term_id,
        "owner_person_id": owner_person_id,
        "sis_section_code": f"SEC-{next_seq():05d}",
        "shell_type": "OFFICIAL",
        "base_seat_cap": DEFAULTS["BASE_SEAT_CAP"],
    }
    payload.update(overrides)
    return payload


# ─── ContentItem ──────────────────────────────────────────────────────────

def create_content_item_payload(shell_id, **overrides) -> dict:
    payload = {
        "shell_id": shell_id,
        "item_type": "ASSIGNMENT",
        "title": DEFAULTS["ITEM_TITLE"],
        "points_possible": 40.00,
        "storage_mb": 0.00,
    }
    payload.update(overrides)
    return payload


# ─── Enrollment ───────────────────────────────────────────────────────────

def create_enrollment_payload(shell_id, person_id, **overrides) -> dict:
    payload = {"shell_id": shell_id, "person_id": person_id, "role": "STUDENT"}
    payload.update(overrides)
    return payload


# ─── EnrollmentSyncBatch ──────────────────────────────────────────────────

def sync_operation(op, shell_id, person_id, role="STUDENT") -> dict:
    return {"op": op, "shell_id": shell_id, "person_id": person_id, "role": role}


def create_sync_batch_payload(term_id, operations, **overrides) -> dict:
    payload = {"term_id": term_id, "operations": operations}
    payload.update(overrides)
    return payload


# ─── MergeRequest ─────────────────────────────────────────────────────────

def create_merge_request_payload(
    parent_shell_id, child_shell_id, expected_parent_shell_version, **overrides
) -> dict:
    payload = {
        "parent_shell_id": parent_shell_id,
        "child_shell_id": child_shell_id,
        "expected_parent_shell_version": expected_parent_shell_version,
    }
    payload.update(overrides)
    return payload


# ─── RolloverJob ──────────────────────────────────────────────────────────

def create_rollover_job_payload(
    source_shell_id, target_shell_id, target_term_id,
    expected_target_shell_version, **overrides
) -> dict:
    payload = {
        "source_shell_id": source_shell_id,
        "target_shell_id": target_shell_id,
        "target_term_id": target_term_id,
        "expected_target_shell_version": expected_target_shell_version,
    }
    payload.update(overrides)
    return payload


# ─── ToolIntegration ──────────────────────────────────────────────────────

def create_tool_integration_payload(**overrides) -> dict:
    n = next_seq()
    payload = {
        "vendor_name": DEFAULTS["VENDOR_NAME"],
        "tool_name": f"{DEFAULTS['TOOL_NAME']}-{n}",
        "tool_version": DEFAULTS["TOOL_VERSION"],
        "data_sharing_scope": "ROSTER_ONLY",
    }
    payload.update(overrides)
    return payload


# ─── ToolReview ───────────────────────────────────────────────────────────

def create_tool_review_payload(tool_id, dimension, decision="CLEAR", **overrides) -> dict:
    payload = {"tool_id": tool_id, "dimension": dimension, "decision": decision}
    payload.update(overrides)
    return payload


# ─── ToolPlacement ────────────────────────────────────────────────────────

def create_tool_placement_payload(tool_id, shell_id, **overrides) -> dict:
    payload = {"tool_id": tool_id, "shell_id": shell_id}
    payload.update(overrides)
    return payload


# ─── GradePassback / GradeDispute ─────────────────────────────────────────

def create_grade_passback_payload(shell_id, **overrides) -> dict:
    payload = {"shell_id": shell_id}
    payload.update(overrides)
    return payload


def create_grade_dispute_payload(
    passback_id, enrollment_id, content_item_id, claimed_earned_points, **overrides
) -> dict:
    payload = {
        "passback_id": passback_id,
        "enrollment_id": enrollment_id,
        "content_item_id": content_item_id,
        "claimed_earned_points": claimed_earned_points,
    }
    payload.update(overrides)
    return payload


# ─── ContinuityWindow ─────────────────────────────────────────────────────

def create_continuity_window_payload(
    term_id, kind, window_start, window_end, expected_term_version, **overrides
) -> dict:
    payload = {
        "term_id": term_id,
        "kind": kind,
        "window_start": window_start,
        "window_end": window_end,
        "expected_term_version": expected_term_version,
    }
    payload.update(overrides)
    return payload


# ─── Underscore-namespace drivers ─────────────────────────────────────────

def set_clock_payload(to_iso8601) -> dict:
    return {"to_iso8601": to_iso8601}


def grade_record_payload(enrollment_id, content_item_id, earned_points) -> dict:
    return {
        "enrollment_id": enrollment_id,
        "content_item_id": content_item_id,
        "earned_points": earned_points,
    }
