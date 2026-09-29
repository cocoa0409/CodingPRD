"""Validation precedence between two rules that a single request breaks at once.

Two pairs are exercised. On a tool review, a duty collision and a duplicate
dimension can both be true of one request, and only one error may come back. On
an enrollment reinstatement, a closed add/drop window and a full shell can both
be true, and again only one error may come back. Each pair is also exercised in
isolation, so the winner cannot be explained away by the loser being missing.

The server is relaunched before every test, so each test builds its own term,
shell, people, tool and reviews from scratch, and the logical clock reads its
startup instant until a test moves it.
"""
from test_helpers import (
    ApiErrorId,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import factories as fac
from test_helpers import fixtures as fx

REVIEWER_X = "rev-x"
REVIEWER_Y = "rev-y"
REVIEWER_Z = "rev-z"

TOOL_METADATA = {
    "vendor_name": "OpenCampus", "tool_name": "PeerNotes", "tool_version": "1.0.0",
    "data_sharing_scope": "ROSTER_ONLY", "pii_tier": 0, "vpat_score": 90.00,
    "wcag_level": "AA",
}

ADD_DROP_DEADLINE = "2026-09-07T00:00:00Z"
AFTER_THE_DEADLINE = "2026-09-20T09:00:00Z"


def _tool_reviewed_by_two_people(api, lms_admin_headers, privacy_headers,
                                 accessibility_headers):
    """A tool UNDER_REVIEW whose PRIVACY dimension was decided by one reviewer and
    whose ACCESSIBILITY dimension was decided by another."""
    tool = validate_success(
        api.create_tool_integration(
            fac.create_tool_integration_payload(**TOOL_METADATA), lms_admin_headers
        ),
        201,
    )
    validate_success(
        api.tool_integration_transition(
            tool["id"], {"action": "OPEN_REVIEW"}, lms_admin_headers
        ),
        200,
    )
    privacy_review = validate_success(
        api.create_tool_review(
            fac.create_tool_review_payload(tool["id"], "PRIVACY", "CLEAR"),
            privacy_headers,
        ),
        201,
    )
    accessibility_review = validate_success(
        api.create_tool_review(
            fac.create_tool_review_payload(tool["id"], "ACCESSIBILITY", "CLEAR"),
            accessibility_headers,
        ),
        201,
    )
    return {
        "tool": tool,
        "privacy_review": privacy_review,
        "accessibility_review": accessibility_review,
        "tool_after_round_one": fx.read_tool(api, tool["id"]),
    }


def _shell_with_a_dropped_row(api, backfill_the_freed_seat):
    """A base_seat_cap 2 shell in an IN_SESSION term whose add/drop deadline is
    pinned, holding one DROPPED row; the freed seat is optionally taken back."""
    term = fx.create_term_in_state(
        api, "IN_SESSION", add_drop_deadline_at=ADD_DROP_DEADLINE
    )
    owner = fx.create_faculty(api)
    requested = fx.request_shell(
        api, term["id"], owner["id"], sis_section_code="CS160-01", base_seat_cap=2
    )
    shell_at_approve = fx.provisioning_decision(api, requested["id"], "APPROVE")
    students = fx.create_students(api, 3)
    first = fx.enrol(api, shell_at_approve["id"], students[0]["id"], "ACTIVE")
    second = fx.enrol(api, shell_at_approve["id"], students[1]["id"], "ACTIVE")
    dropped = fx.transition_enrollment(
        api, first["id"], "DROP", reason="schedule conflict"
    )
    backfill = None
    if backfill_the_freed_seat:
        backfill = fx.enrol(api, shell_at_approve["id"], students[2]["id"], "ACTIVE")
    return {
        "term": term,
        "shell_at_approve": shell_at_approve,
        "dropped": dropped,
        "second_seat": second,
        "backfill": backfill,
        "shell_now": fx.read_shell(api, shell_at_approve["id"]),
    }


def test_reviewer_user_id_is_recorded_from_the_acting_header(
    api, lms_admin_headers, privacy_reviewer_headers_for,
    accessibility_reviewer_headers_for
):
    """PRD §2.1: "When `X-User-Role` is `Registrar`, `LmsAdmin`,
    `PrivacyReviewer`, or `AccessibilityReviewer`, `X-User-ID` is an opaque
    operator identifier not tied to any persisted entity."
    PRD §2.1: "The server records it where a transition says so — as
    `submitted_by_user_id` and `decided_by_user_id` on a `MergeRequest`, and as
    `reviewer_user_id` on a `ToolReview` — and compares it to other recorded
    operator identifiers for segregation-of-duties purposes, but never compares it
    to any entity's `id`."
    PRD §3.7: "A `CLEAR` decision moves that dimension `PENDING` → `CLEARED`,
    `CONDITIONS` moves it `PENDING` → `CONDITIONAL`, and `BLOCK` moves it
    `PENDING` → `BLOCKED`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_review_dimension_conflict_on_tool_reviews
    """
    world = _tool_reviewed_by_two_people(
        api,
        lms_admin_headers,
        privacy_reviewer_headers_for(REVIEWER_X),
        accessibility_reviewer_headers_for(REVIEWER_Y),
    )

    assert world["privacy_review"]["reviewer_user_id"] == REVIEWER_X, (
        "reviewer_user_id is taken from the acting X-User-ID header, never from "
        f"the request body, got {world['privacy_review']['reviewer_user_id']}"
    )
    assert world["accessibility_review"]["reviewer_user_id"] == REVIEWER_Y

    assert world["tool_after_round_one"]["privacy_review_state"] == "CLEARED"
    assert world["tool_after_round_one"]["accessibility_review_state"] == "CLEARED"
    assert world["tool_after_round_one"]["approval_state"] == "UNDER_REVIEW"


def test_duty_collision_outranks_the_duplicate_dimension_on_one_review_request(
    api, lms_admin_headers, privacy_reviewer_headers_for,
    accessibility_reviewer_headers_for
):
    """PRD §2.10: "When several rules could reject the same request, exactly one of
    them decides the response, and the order is fixed."
    PRD §2.10: "Enumerated in full, lowest number evaluated first:"
    PRD §2.10: "Segregation of duties as described in §2.9, on
    `POST /merge-requests/{id}/transitions` with action `APPROVE` or `DECLINE`, on
    `POST /tool-reviews`, and on `POST /grade-passbacks/{id}/registrar-decisions` —
    otherwise `ERR_SEGREGATION_OF_DUTIES`."
    PRD §2.10: "A tool holds at most one review per dimension within one review
    round, on `POST /tool-reviews` — otherwise `ERR_REVIEW_DIMENSION_CONFLICT`."
    PRD §2.9: "The reviewer who decided one dimension of a tool's review may not
    decide the other dimension of the same tool."
    PRD §3.7: "The two dimensions must also be decided by two different people: the
    acting user may not be the `reviewer_user_id` recorded on this tool's review in
    the *other* dimension, otherwise `ERR_SEGREGATION_OF_DUTIES`."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_review_dimension_conflict_on_tool_reviews
    """
    world = _tool_reviewed_by_two_people(
        api,
        lms_admin_headers,
        privacy_reviewer_headers_for(REVIEWER_X),
        accessibility_reviewer_headers_for(REVIEWER_Y),
    )
    tool_id = world["tool"]["id"]

    both_broken = api.create_tool_review(
        fac.create_tool_review_payload(tool_id, "ACCESSIBILITY", "BLOCK"),
        accessibility_reviewer_headers_for(REVIEWER_X),
    )
    validate_error(both_broken, ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value)

    only_the_duplicate = api.create_tool_review(
        fac.create_tool_review_payload(tool_id, "PRIVACY", "BLOCK"),
        privacy_reviewer_headers_for(REVIEWER_Z),
    )
    validate_error(only_the_duplicate, ApiErrorId.ERR_REVIEW_DIMENSION_CONFLICT.value)


def test_neither_rejected_review_leaves_a_trace_on_the_tool_or_its_history(
    api, lms_admin_headers, privacy_reviewer_headers_for,
    accessibility_reviewer_headers_for
):
    """PRD §2.10: "When several rules could reject the same request, exactly one of
    them decides the response, and the order is fixed."
    PRD §3.7: "A review row is a permanent record: it carries only its own
    identifier and its creation timestamp, it is never edited, never deleted and
    carries no row version of its own — the audit trail is append-only."
    PRD §3.7: "A `CLEAR` decision moves that dimension `PENDING` → `CLEARED`,
    `CONDITIONS` moves it `PENDING` → `CONDITIONAL`, and `BLOCK` moves it
    `PENDING` → `BLOCKED`."
    PRD §2.4: "Almost every record additionally carries `updated_at` — the same
    timestamp format, refreshed on every mutation — and `version`, an integer that
    starts at 1 on creation and increments by exactly one on every mutation of that
    record."

    Design: Difficulty/priority_pair_validation_conflict/segregation_of_duties_outranks_review_dimension_conflict_on_tool_reviews
    """
    world = _tool_reviewed_by_two_people(
        api,
        lms_admin_headers,
        privacy_reviewer_headers_for(REVIEWER_X),
        accessibility_reviewer_headers_for(REVIEWER_Y),
    )
    tool_id = world["tool"]["id"]
    version_before = world["tool_after_round_one"]["version"]

    validate_error(
        api.create_tool_review(
            fac.create_tool_review_payload(tool_id, "ACCESSIBILITY", "BLOCK"),
            accessibility_reviewer_headers_for(REVIEWER_X),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )
    validate_error(
        api.create_tool_review(
            fac.create_tool_review_payload(tool_id, "PRIVACY", "BLOCK"),
            privacy_reviewer_headers_for(REVIEWER_Z),
        ),
        ApiErrorId.ERR_REVIEW_DIMENSION_CONFLICT.value,
    )

    tool_after = fx.read_tool(api, tool_id)
    assert tool_after["privacy_review_state"] == "CLEARED", (
        "neither refused BLOCK moved a verdict dimension"
    )
    assert tool_after["accessibility_review_state"] == "CLEARED"
    assert tool_after["approval_state"] == "UNDER_REVIEW"
    assert tool_after["version"] == version_before, (
        "a refused request mutates nothing, so the tool's version must not move, "
        f"expected {version_before} and got {tool_after['version']}"
    )

    rows, _meta = validate_paginated(
        api.list_tool_reviews(lms_admin_headers, params={"tool_id": tool_id})
    )
    assert len(rows) == 2, (
        f"a rejected review must not be persisted, got {len(rows)} rows"
    )
    assert {row["id"] for row in rows} == {
        world["privacy_review"]["id"], world["accessibility_review"]["id"]
    }


def test_the_pinned_deadline_and_the_full_shell_are_both_in_place(api):
    """PRD §3.1: "`add_drop_deadline_at` is the last instant at which a dropped
    enrollment may be reinstated, and defaults to fourteen days after
    `term_start_at`."
    PRD §3.3: "On approval `effective_seat_cap` is set equal to `base_seat_cap`,
    `publish_readiness` is set to true, and `sandbox_expires_at` is set to sixty days
    after the term's `term_end_at` for a `SANDBOX` or `DEV` shell while remaining
    null for an `OFFICIAL` one."
    PRD §3.4: "The new row opens in `enrollment_state` `ACTIVE`; when its `role` is
    `STUDENT` the shell's `active_enrollment_count` and the term's
    `total_active_enrollments` each rise by one, and the shell's
    `seat_utilization_pct` and `overflow_flag` are re-derived."
    PRD §3.4: "**Dropping** takes `ACTIVE` → `DROPPED` and needs only that the shell
    be `PROVISIONED` or `PUBLISHED` (otherwise `ERR_SHELL_STATE_BLOCKS_ENROLLMENT`)."

    Design: Difficulty/priority_pair_validation_conflict/add_drop_window_closed_outranks_seat_cap_exceeded_on_enrollment_reinstate
    """
    world = _shell_with_a_dropped_row(api, backfill_the_freed_seat=True)

    assert world["term"]["add_drop_deadline_at"] == ADD_DROP_DEADLINE, (
        "the supplied add/drop deadline is echoed back verbatim, got "
        f"{world['term']['add_drop_deadline_at']}"
    )
    assert world["shell_now"]["effective_seat_cap"] == 2
    assert world["shell_now"]["active_enrollment_count"] == 2, (
        "the backfilling student took the freed seat, so the shell is full again"
    )
    assert world["dropped"]["enrollment_state"] == "DROPPED"


def test_inside_the_window_a_full_shell_refuses_the_reinstatement_on_capacity(
    api, registrar_headers
):
    """PRD §2.10: "A student enrollment may occupy a seat only while at least one
    seat is open under the shell's effective capacity, on `POST /enrollments` and on
    `POST /enrollments/{id}/transitions` with action `PROMOTE` or `REINSTATE` —
    otherwise `ERR_SEAT_CAP_EXCEEDED`."
    PRD §3.4: "It requires the logical clock to be at or before the term's
    `add_drop_deadline_at` (otherwise `ERR_ADD_DROP_WINDOW_CLOSED`), the shell to be
    `PROVISIONED` or `PUBLISHED` (otherwise `ERR_SHELL_STATE_BLOCKS_ENROLLMENT`),
    and — for a `STUDENT` row — the shell's `active_enrollment_count` to still be
    below its `effective_seat_cap` (otherwise `ERR_SEAT_CAP_EXCEEDED`)."
    PRD §2.5: "On startup the logical clock reads exactly `2026-08-01T00:00:00Z`,
    and it never falls back to real time."

    Design: Difficulty/priority_pair_validation_conflict/add_drop_window_closed_outranks_seat_cap_exceeded_on_enrollment_reinstate
    """
    world = _shell_with_a_dropped_row(api, backfill_the_freed_seat=True)

    refused = api.enrollment_transition(
        world["dropped"]["id"],
        {"action": "REINSTATE", "reason": "advisor override, inside the window"},
        registrar_headers,
    )
    validate_error(refused, ApiErrorId.ERR_SEAT_CAP_EXCEEDED.value)

    untouched = fx.read_enrollment(api, world["dropped"]["id"])
    assert untouched["enrollment_state"] == "DROPPED"
    assert untouched["reinstatement_count"] == 0


def test_the_closed_window_outranks_the_full_shell_and_also_stands_alone(
    api, registrar_headers, lms_admin_headers
):
    """PRD §2.10: "When several rules could reject the same request, exactly one of
    them decides the response, and the order is fixed."
    PRD §2.10: "Enumerated in full, lowest number evaluated first:"
    PRD §2.10: "Reinstating a dropped enrollment happens at or before the term's
    `add_drop_deadline_at`, on `POST /enrollments/{id}/transitions` with action
    `REINSTATE` — otherwise `ERR_ADD_DROP_WINDOW_CLOSED`."
    PRD §2.10: "A student enrollment may occupy a seat only while at least one seat
    is open under the shell's effective capacity, on `POST /enrollments` and on
    `POST /enrollments/{id}/transitions` with action `PROMOTE` or `REINSTATE` —
    otherwise `ERR_SEAT_CAP_EXCEEDED`."
    PRD §2.5: "An `LmsAdmin` may move it by supplying a `to_iso8601` instant to the
    clock-setting capability; that operation mutates no entity, but every subsequent
    request evaluates `add_drop_deadline_at`, `sandbox_expires_at`,
    `student_access_end_at`, `retention_purge_at`, `access_revoked_at` and continuity
    window bounds against the new instant."
    PRD §3.4: "It requires the logical clock to be at or before the term's
    `add_drop_deadline_at` (otherwise `ERR_ADD_DROP_WINDOW_CLOSED`), the shell to be
    `PROVISIONED` or `PUBLISHED` (otherwise `ERR_SHELL_STATE_BLOCKS_ENROLLMENT`),
    and — for a `STUDENT` row — the shell's `active_enrollment_count` to still be
    below its `effective_seat_cap` (otherwise `ERR_SEAT_CAP_EXCEEDED`)."

    Design: Difficulty/priority_pair_validation_conflict/add_drop_window_closed_outranks_seat_cap_exceeded_on_enrollment_reinstate
    """
    world = _shell_with_a_dropped_row(api, backfill_the_freed_seat=True)
    fx.advance_clock(api, AFTER_THE_DEADLINE, headers=lms_admin_headers)

    both_broken = api.enrollment_transition(
        world["dropped"]["id"],
        {"action": "REINSTATE", "reason": "advisor override, both rules violated"},
        registrar_headers,
    )
    validate_error(both_broken, ApiErrorId.ERR_ADD_DROP_WINDOW_CLOSED.value)

    freed = fx.transition_enrollment(
        api, world["backfill"]["id"], "DROP",
        reason="freeing the seat to isolate the temporal rule",
    )
    assert freed["enrollment_state"] == "DROPPED"

    only_the_window = api.enrollment_transition(
        world["dropped"]["id"],
        {"action": "REINSTATE", "reason": "advisor override, only the window is closed"},
        registrar_headers,
    )
    validate_error(only_the_window, ApiErrorId.ERR_ADD_DROP_WINDOW_CLOSED.value)

    final = fx.read_enrollment(api, world["dropped"]["id"])
    assert final["enrollment_state"] == "DROPPED", (
        "none of the refused reinstatements moved the row"
    )
    assert final["reinstatement_count"] == 0

    shell_after = fx.read_shell(api, world["shell_at_approve"]["id"])
    assert shell_after["active_enrollment_count"] == 1, (
        "only the isolating drop changed the roster, and no waitlist existed to "
        f"absorb the freed seat, got {shell_after['active_enrollment_count']}"
    )
    term_after = fx.read_term(api, world["term"]["id"])
    assert term_after["total_active_enrollments"] == 1


def test_the_add_drop_boundary_instant_itself_still_admits_a_reinstatement(
    api, registrar_headers, lms_admin_headers
):
    """PRD §2.10: "Reinstating a dropped enrollment happens at or before the term's
    `add_drop_deadline_at`, on `POST /enrollments/{id}/transitions` with action
    `REINSTATE` — otherwise `ERR_ADD_DROP_WINDOW_CLOSED`."
    PRD §3.4: "**Reinstatement** takes `DROPPED` → `ACTIVE` and closes that cycle,
    bounded by the calendar rather than by any loop counter."
    PRD §3.4: "It increments `reinstatement_count` by one, sets `dropped_at` back to
    null, and for a `STUDENT` row raises the shell's `active_enrollment_count` and
    the term's `total_active_enrollments` by one each while re-deriving
    `seat_utilization_pct` and `overflow_flag`."

    Design: Difficulty/priority_pair_validation_conflict/add_drop_window_closed_outranks_seat_cap_exceeded_on_enrollment_reinstate
    """
    world = _shell_with_a_dropped_row(api, backfill_the_freed_seat=False)
    assert world["shell_now"]["active_enrollment_count"] == 1, (
        "the freed seat is left open so that only the calendar rule is in play"
    )
    fx.advance_clock(api, ADD_DROP_DEADLINE, headers=lms_admin_headers)

    reinstated = validate_success(
        api.enrollment_transition(
            world["dropped"]["id"],
            {"action": "REINSTATE", "reason": "advisor override, at the boundary"},
            registrar_headers,
        ),
        200,
    )
    assert reinstated["enrollment_state"] == "ACTIVE", (
        "the deadline is inclusive, so a clock reading exactly "
        f"{ADD_DROP_DEADLINE} is still inside the add/drop window"
    )
    assert reinstated["reinstatement_count"] == 1
    assert reinstated["dropped_at"] is None

    shell_after = fx.read_shell(api, world["shell_at_approve"]["id"])
    assert shell_after["active_enrollment_count"] == 2
    term_after = fx.read_term(api, world["term"]["id"])
    assert term_after["total_active_enrollments"] == 2
