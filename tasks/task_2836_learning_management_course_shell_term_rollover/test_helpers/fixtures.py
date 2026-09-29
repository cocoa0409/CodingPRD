"""Composite setup helpers.

The server is restarted before every individual test, so every test starts
against an empty database. Each helper below therefore builds its preconditions
from scratch using only the endpoints the PRD declares, and returns the raw
response payloads so a test can assert on them directly.

Every helper takes the ApiClient as its first argument, unwraps the success
envelope with get_success_data(), and threads identity through the X-User-ID /
X-User-Role headers the PRD requires.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories as fac
from .constants import (
    SOURCE_TERM_END,
    SOURCE_TERM_START,
    TARGET_TERM_END,
    TARGET_TERM_START,
)
from .test_users import (
    ACCESSIBILITY_REVIEWER_USER_ID,
    PRIVACY_REVIEWER_USER_ID,
    TEST_USERS,
    make_accessibility_reviewer_headers,
    make_instructor_headers,
    make_privacy_reviewer_headers,
    make_student_headers,
)

REGISTRAR = TEST_USERS["registrar_headers"]
LMS_ADMIN = TEST_USERS["lms_admin_headers"]

#: The forward lifecycle path of an AcademicTerm, in PRD order.
TERM_FORWARD_PATH = [
    "PLANNING",
    "REGISTRATION_OPEN",
    "IN_SESSION",
    "FINALS",
    "GRADING",
    "CLOSED",
    "ARCHIVED",
]


# ─── logical clock ────────────────────────────────────────────────────────

def advance_clock(api, to_iso8601, headers=None):
    """Move the server's logical clock to an explicit instant."""
    return get_success_data(
        api.set_clock(fac.set_clock_payload(to_iso8601), headers or LMS_ADMIN)
    )


# ─── AcademicTerm ─────────────────────────────────────────────────────────

def create_term(api, headers=None, **overrides):
    """Register one AcademicTerm; it starts in PLANNING / NORMAL."""
    return get_success_data(
        api.create_academic_term(
            fac.create_academic_term_payload(**overrides), headers or REGISTRAR
        )
    )


def transition_term(api, term_id, target_state, headers=None):
    """Drive one lifecycle edge on a term and return the updated row."""
    return get_success_data(
        api.term_lifecycle_transition(
            term_id, {"target_state": target_state}, headers or REGISTRAR
        )
    )


def walk_term_to(api, term_id, target_state, headers=None):
    """Walk the term forward one edge at a time until it reaches target_state."""
    stop = TERM_FORWARD_PATH.index(target_state)
    row = None
    for state in TERM_FORWARD_PATH[1:stop + 1]:
        row = transition_term(api, term_id, state, headers)
    if row is None:
        row = get_success_data(api.get_academic_term(term_id, headers or REGISTRAR))
    return row


def create_term_in_state(api, target_state, headers=None, **overrides):
    """Create a term and walk its lifecycle dimension to target_state."""
    term = create_term(api, headers=headers, **overrides)
    if target_state != "PLANNING":
        term = walk_term_to(api, term["id"], target_state, headers)
    return term


def change_posture(api, term_id, target_posture, reason="continuity drill", headers=None):
    """Move the term's independent continuity_posture dimension."""
    return get_success_data(
        api.term_posture_change(
            term_id,
            {"target_posture": target_posture, "reason": reason},
            headers or LMS_ADMIN,
        )
    )


def escalate_posture_to(api, term_id, target_posture, headers=None):
    """Walk NORMAL -> ELEVATED -> CONTINUITY_MODE one edge at a time."""
    path = ["NORMAL", "ELEVATED", "CONTINUITY_MODE"]
    stop = path.index(target_posture)
    row = None
    for posture in path[1:stop + 1]:
        row = change_posture(api, term_id, posture, headers=headers)
    if row is None:
        row = get_success_data(api.get_academic_term(term_id, headers or REGISTRAR))
    return row


def read_term(api, term_id, headers=None):
    return get_success_data(api.get_academic_term(term_id, headers or REGISTRAR))


# ─── Person ───────────────────────────────────────────────────────────────

def create_faculty(api, headers=None, **overrides):
    """Register a FACULTY person (the identity an Instructor call travels as)."""
    return get_success_data(
        api.create_person(fac.create_person_payload(**overrides), headers or REGISTRAR)
    )


def create_student(api, headers=None, **overrides):
    """Register a STUDENT person."""
    return get_success_data(
        api.create_person(
            fac.create_student_person_payload(**overrides), headers or REGISTRAR
        )
    )


def create_students(api, count, headers=None, **overrides):
    """Register `count` STUDENT people and return them in creation order."""
    return [create_student(api, headers=headers, **overrides) for _ in range(count)]


def read_person(api, person_id, headers=None):
    return get_success_data(api.get_person(person_id, headers or REGISTRAR))


# ─── CourseShell ──────────────────────────────────────────────────────────

def request_shell(api, term_id, owner_person_id, headers=None, **overrides):
    """Request a shell; it lands in REQUESTED."""
    return get_success_data(
        api.create_course_shell(
            fac.create_course_shell_payload(term_id, owner_person_id, **overrides),
            headers or LMS_ADMIN,
        )
    )


def provisioning_decision(api, shell_id, decision, headers=None, **extra):
    payload = {"decision": decision}
    payload.update(extra)
    return get_success_data(
        api.shell_provisioning_decision(shell_id, payload, headers or LMS_ADMIN)
    )


def provision_shell(api, term_id, owner_person_id, headers=None, **overrides):
    """Request a shell and APPROVE it, leaving it PROVISIONED."""
    shell = request_shell(api, term_id, owner_person_id, headers=headers, **overrides)
    return provisioning_decision(api, shell["id"], "APPROVE", headers=headers)


def publish(api, shell_id, headers=None, payload=None):
    return get_success_data(api.publish_shell(shell_id, headers or LMS_ADMIN, payload))


def unpublish(api, shell_id, reason="instructor request", headers=None):
    return get_success_data(
        api.unpublish_shell(shell_id, headers or LMS_ADMIN, {"reason": reason})
    )


def transition_shell(api, shell_id, target_state, headers=None, **extra):
    payload = {"target_state": target_state}
    payload.update(extra)
    return get_success_data(
        api.shell_lifecycle_transition(shell_id, payload, headers or REGISTRAR)
    )


def read_shell(api, shell_id, headers=None):
    return get_success_data(api.get_course_shell(shell_id, headers or LMS_ADMIN))


def provisioned_shell_setup(api, term_state="IN_SESSION", term_overrides=None,
                            shell_overrides=None):
    """Term + faculty owner + PROVISIONED OFFICIAL shell, the common baseline.

    Returns {"term", "owner", "shell", "instructor_headers"}.
    """
    term = create_term_in_state(api, term_state, **(term_overrides or {}))
    owner = create_faculty(api)
    shell = provision_shell(api, term["id"], owner["id"], **(shell_overrides or {}))
    return {
        "term": term,
        "owner": owner,
        "shell": shell,
        "instructor_headers": make_instructor_headers(owner["id"]),
    }


def published_shell_setup(api, term_state="IN_SESSION", term_overrides=None,
                          shell_overrides=None):
    """Same as provisioned_shell_setup but the shell is PUBLISHED."""
    setup = provisioned_shell_setup(api, term_state, term_overrides, shell_overrides)
    setup["shell"] = publish(api, setup["shell"]["id"])
    return setup


# ─── Enrollment ───────────────────────────────────────────────────────────

def enrol(api, shell_id, person_id, requested_state="ACTIVE", role="STUDENT",
          headers=None, **overrides):
    """Create one enrollment straight to ACTIVE or onto the waitlist."""
    return get_success_data(
        api.create_enrollment(
            fac.create_enrollment_payload(
                shell_id, person_id, role=role,
                requested_state=requested_state, **overrides
            ),
            headers or REGISTRAR,
        )
    )


def enrol_new_students(api, shell_id, count, requested_state="ACTIVE"):
    """Register `count` fresh students and enrol each one.

    Returns a list of (person, enrollment) pairs in creation order.
    """
    pairs = []
    for _ in range(count):
        person = create_student(api)
        pairs.append((person, enrol(api, shell_id, person["id"], requested_state)))
    return pairs


def transition_enrollment(api, enrollment_id, action, reason=None, headers=None,
                          **extra):
    payload = {"action": action}
    if reason is not None:
        payload["reason"] = reason
    payload.update(extra)
    return get_success_data(
        api.enrollment_transition(enrollment_id, payload, headers or REGISTRAR)
    )


def read_enrollment(api, enrollment_id, headers=None):
    return get_success_data(api.get_enrollment(enrollment_id, headers or REGISTRAR))


# ─── EnrollmentSyncBatch ──────────────────────────────────────────────────

def stage_sync_batch(api, term_id, operations, headers=None, **overrides):
    return get_success_data(
        api.create_sync_batch(
            fac.create_sync_batch_payload(term_id, operations, **overrides),
            headers or REGISTRAR,
        )
    )


def transition_sync_batch(api, batch_id, action, headers=None, **extra):
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(
        api.sync_batch_transition(batch_id, payload, headers or REGISTRAR)
    )


def apply_sync_batch(api, term_id, operations, **overrides):
    """Stage -> VALIDATE -> APPLY in one call; returns the applied batch."""
    batch = stage_sync_batch(api, term_id, operations, **overrides)
    transition_sync_batch(api, batch["id"], "VALIDATE")
    return transition_sync_batch(api, batch["id"], "APPLY")


# ─── ContentItem ──────────────────────────────────────────────────────────

def create_content_item(api, shell_id, headers=None, **overrides):
    """Add a content item to a shell (Instructor identity must own the shell)."""
    return get_success_data(
        api.create_content_item(
            fac.create_content_item_payload(shell_id, **overrides),
            headers or LMS_ADMIN,
        )
    )


def patch_content_item(api, item_id, payload, headers):
    return get_success_data(api.patch_content_item(item_id, payload, headers))


def record_submission(api, item_id, enrollment_id, headers, **extra):
    payload = {"enrollment_id": enrollment_id}
    payload.update(extra)
    return get_success_data(api.create_submission(item_id, payload, headers))


def read_content_item(api, item_id, headers=None):
    return get_success_data(api.get_content_item(item_id, headers or LMS_ADMIN))


# ─── ToolIntegration / ToolReview / ToolPlacement ─────────────────────────

#: Metadata whose risk_score is 13.00 — below the CONDITIONAL threshold, so a
#: two-CLEAR review round finalises straight to APPROVED.
LOW_RISK_TOOL_METADATA = {
    "data_sharing_scope": "ROSTER_ONLY",
    "pii_tier": 0,
    "vpat_score": 90.00,
    "wcag_level": "AA",
}


def register_tool(api, headers=None, low_risk=True, **overrides):
    """Register a ToolIntegration; it starts in DRAFT with both dimensions PENDING."""
    base = dict(LOW_RISK_TOOL_METADATA) if low_risk else {}
    base.update(overrides)
    return get_success_data(
        api.create_tool_integration(
            fac.create_tool_integration_payload(**base), headers or LMS_ADMIN
        )
    )


def transition_tool(api, tool_id, action, headers=None, **extra):
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(
        api.tool_integration_transition(tool_id, payload, headers or LMS_ADMIN)
    )


def file_review(api, tool_id, dimension, decision="CLEAR", user_id=None,
                headers=None, **overrides):
    """File one dimension's verdict. reviewer_user_id comes from X-User-ID."""
    if headers is None:
        if dimension == "PRIVACY":
            headers = make_privacy_reviewer_headers(
                user_id or PRIVACY_REVIEWER_USER_ID
            )
        else:
            headers = make_accessibility_reviewer_headers(
                user_id or ACCESSIBILITY_REVIEWER_USER_ID
            )
    return get_success_data(
        api.create_tool_review(
            fac.create_tool_review_payload(tool_id, dimension, decision, **overrides),
            headers,
        )
    )


def tool_under_review(api, **overrides):
    """Register a tool and move it DRAFT -> UNDER_REVIEW."""
    tool = register_tool(api, **overrides)
    return transition_tool(api, tool["id"], "OPEN_REVIEW")


def approved_tool(api, privacy_decision="CLEAR", accessibility_decision="CLEAR",
                  **overrides):
    """Register, review both dimensions with distinct reviewers, and finalise."""
    tool = tool_under_review(api, **overrides)
    file_review(api, tool["id"], "PRIVACY", privacy_decision)
    file_review(api, tool["id"], "ACCESSIBILITY", accessibility_decision)
    return transition_tool(api, tool["id"], "FINALIZE_REVIEW")


def read_tool(api, tool_id, headers=None):
    return get_success_data(api.get_tool_integration(tool_id, headers or LMS_ADMIN))


def request_placement(api, tool_id, shell_id, headers=None, **overrides):
    """Request a placement; it lands in REQUESTED."""
    return get_success_data(
        api.create_tool_placement(
            fac.create_tool_placement_payload(tool_id, shell_id, **overrides),
            headers or LMS_ADMIN,
        )
    )


def transition_placement(api, placement_id, action, headers=None, **extra):
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(
        api.tool_placement_transition(placement_id, payload, headers or LMS_ADMIN)
    )


def active_placement(api, tool_id, shell_id, headers=None, **overrides):
    """Request and ACTIVATE a placement, pinning the tool's approved version."""
    placement = request_placement(api, tool_id, shell_id, headers=headers, **overrides)
    return transition_placement(api, placement["id"], "ACTIVATE", headers=headers)


def read_placement(api, placement_id, headers=None):
    return get_success_data(api.get_tool_placement(placement_id, headers or LMS_ADMIN))


# ─── MergeRequest ─────────────────────────────────────────────────────────

def open_merge_request(api, parent_shell, child_shell_id, headers=None, **overrides):
    """Open a cross-list request, guarded on the parent shell's current version."""
    return get_success_data(
        api.create_merge_request(
            fac.create_merge_request_payload(
                parent_shell["id"], child_shell_id, parent_shell["version"], **overrides
            ),
            headers or LMS_ADMIN,
        )
    )


def transition_merge_request(api, merge_id, action, headers=None, **extra):
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(
        api.merge_request_transition(merge_id, payload, headers or LMS_ADMIN)
    )


def approved_merge_request(api, parent_shell, child_shell_id, **overrides):
    """Open -> SUBMIT -> APPROVE, leaving the request ready to APPLY."""
    merge = open_merge_request(api, parent_shell, child_shell_id, **overrides)
    transition_merge_request(api, merge["id"], "SUBMIT")
    return transition_merge_request(api, merge["id"], "APPROVE")


def read_merge_request(api, merge_id, headers=None):
    return get_success_data(api.get_merge_request(merge_id, headers or LMS_ADMIN))


# ─── RolloverJob ──────────────────────────────────────────────────────────

def open_rollover_job(api, source_shell_id, target_shell, target_term_id,
                      headers=None, **overrides):
    """Open a rollover job, guarded on the target shell's current version."""
    return get_success_data(
        api.create_rollover_job(
            fac.create_rollover_job_payload(
                source_shell_id, target_shell["id"], target_term_id,
                target_shell["version"], **overrides
            ),
            headers or LMS_ADMIN,
        )
    )


def transition_rollover_job(api, job_id, action, headers=None, **extra):
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(
        api.rollover_job_transition(job_id, payload, headers or LMS_ADMIN)
    )


def validated_rollover_job(api, source_shell_id, target_shell, target_term_id,
                           **overrides):
    """Open a job and VALIDATE it, leaving it ready to EXECUTE."""
    job = open_rollover_job(
        api, source_shell_id, target_shell, target_term_id, **overrides
    )
    return transition_rollover_job(api, job["id"], "VALIDATE")


def read_rollover_job(api, job_id, headers=None):
    return get_success_data(api.get_rollover_job(job_id, headers or LMS_ADMIN))


def rollover_pair_setup(api, source_items=None, target_count=1,
                        source_term_overrides=None, target_term_overrides=None):
    """A CONCLUDED source shell with content and N empty PROVISIONED targets.

    `source_items` is a list of keyword dicts, each forwarded to the content-item
    factory, created by the owning instructor before the source shell concludes.
    Returns {"source_term", "target_term", "owner", "instructor_headers",
             "source_shell", "source_items", "target_shells"}.
    """
    src_term = create_term(
        api,
        term_start_at=SOURCE_TERM_START,
        term_end_at=SOURCE_TERM_END,
        **(source_term_overrides or {}),
    )
    tgt_term = create_term(
        api,
        term_start_at=TARGET_TERM_START,
        term_end_at=TARGET_TERM_END,
        **(target_term_overrides or {}),
    )
    owner = create_faculty(api)
    instructor_headers = make_instructor_headers(owner["id"])
    src_shell = provision_shell(api, src_term["id"], owner["id"])
    items = [
        create_content_item(api, src_shell["id"], instructor_headers, **spec)
        for spec in (source_items or [])
    ]
    src_shell = transition_shell(api, src_shell["id"], "CONCLUDED")
    targets = [
        provision_shell(api, tgt_term["id"], owner["id"]) for _ in range(target_count)
    ]
    return {
        "source_term": src_term,
        "target_term": tgt_term,
        "owner": owner,
        "instructor_headers": instructor_headers,
        "source_shell": src_shell,
        "source_items": items,
        "target_shells": targets,
    }


# ─── grades, passbacks and disputes ───────────────────────────────────────

def record_grade(api, enrollment_id, content_item_id, earned_points, headers):
    """Record one enrollment's earned points for one item (Instructor only)."""
    return get_success_data(
        api.record_grade(
            fac.grade_record_payload(enrollment_id, content_item_id, earned_points),
            headers,
        )
    )


def stage_passback(api, shell_id, headers, **overrides):
    """Stage the shell's gradebook; the passback lands in STAGED."""
    return get_success_data(
        api.create_grade_passback(
            fac.create_grade_passback_payload(shell_id, **overrides), headers
        )
    )


def transition_passback(api, passback_id, action, headers, **extra):
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(
        api.grade_passback_transition(passback_id, payload, headers)
    )


def registrar_decide_passback(api, passback_id, decision, note="figures reconciled",
                              headers=None):
    return get_success_data(
        api.registrar_decision(
            passback_id, {"decision": decision, "note": note}, headers or REGISTRAR
        )
    )


def accepted_passback(api, shell_id, instructor_headers, registrar_headers=None):
    """Stage -> SUBMIT -> registrar ACCEPT, leaving the passback ACCEPTED."""
    passback = stage_passback(api, shell_id, instructor_headers)
    transition_passback(api, passback["id"], "SUBMIT", instructor_headers)
    return registrar_decide_passback(
        api, passback["id"], "ACCEPT", headers=registrar_headers
    )


def read_passback(api, passback_id, headers=None):
    return get_success_data(api.get_grade_passback(passback_id, headers or REGISTRAR))


def file_dispute(api, passback_id, enrollment_id, content_item_id,
                 claimed_earned_points, student_person_id, **overrides):
    """A student disputes one graded item on an accepted passback."""
    return get_success_data(
        api.create_grade_dispute(
            fac.create_grade_dispute_payload(
                passback_id, enrollment_id, content_item_id,
                claimed_earned_points, **overrides
            ),
            make_student_headers(student_person_id),
        )
    )


def resolve_dispute(api, dispute_id, outcome, headers, note="regrade complete",
                    **extra):
    payload = {"outcome": outcome, "note": note}
    payload.update(extra)
    return get_success_data(api.resolve_grade_dispute(dispute_id, payload, headers))


def read_dispute(api, dispute_id, headers=None):
    return get_success_data(api.get_grade_dispute(dispute_id, headers or REGISTRAR))


def graded_shell_setup(api, points_possible=200.00, grades=(160.00, 90.00),
                       shell_overrides=None):
    """A PUBLISHED shell in a FINALS term whose gradebook is fully recorded.

    Returns {"term", "owner", "instructor_headers", "shell", "item",
             "students", "enrollments"} where students[i] is graded grades[i].
    """
    setup = published_shell_setup(api, "IN_SESSION", shell_overrides=shell_overrides)
    instructor_headers = setup["instructor_headers"]
    item = create_content_item(
        api, setup["shell"]["id"], instructor_headers,
        points_possible=points_possible, storage_mb=0.00,
    )
    students, enrollments = [], []
    for earned in grades:
        person = create_student(api)
        enrollment = enrol(api, setup["shell"]["id"], person["id"], "ACTIVE")
        record_grade(api, enrollment["id"], item["id"], earned, instructor_headers)
        students.append(person)
        enrollments.append(enrollment)
    term = transition_term(api, setup["term"]["id"], "FINALS")
    return {
        "term": term,
        "owner": setup["owner"],
        "instructor_headers": instructor_headers,
        "shell": read_shell(api, setup["shell"]["id"]),
        "item": item,
        "students": students,
        "enrollments": enrollments,
    }


# ─── ContinuityWindow ─────────────────────────────────────────────────────

def open_window(api, term, kind, window_start, window_end, headers=None, **overrides):
    """Open a continuity window, guarded on the term's current version."""
    return get_success_data(
        api.create_continuity_window(
            fac.create_continuity_window_payload(
                term["id"], kind, window_start, window_end, term["version"], **overrides
            ),
            headers or LMS_ADMIN,
        )
    )


def open_window_for(api, term_id, kind, window_start, window_end, headers=None,
                    **overrides):
    """Same as open_window but re-reads the term to pick up its live version."""
    term = read_term(api, term_id)
    return open_window(
        api, term, kind, window_start, window_end, headers=headers, **overrides
    )


def transition_window(api, window_id, action, headers=None, **extra):
    payload = {"action": action}
    payload.update(extra)
    return get_success_data(
        api.continuity_window_transition(window_id, payload, headers or LMS_ADMIN)
    )


def read_window(api, window_id, headers=None):
    return get_success_data(api.get_continuity_window(window_id, headers or LMS_ADMIN))


# ─── generic helpers ──────────────────────────────────────────────────────

def rows_of(response):
    """The `data` list of a paginated list response."""
    return get_success_data(response)


def ids_of(response):
    return [row["id"] for row in get_success_data(response)]
