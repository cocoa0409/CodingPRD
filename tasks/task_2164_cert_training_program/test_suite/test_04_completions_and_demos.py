"""Attendance recording, the skills demonstration and the withdrawal of evidence."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_hours,
    assert_instant,
    assert_score,
    create_module_completion_payload,
    deliver_session,
    make_evaluator_headers,
    make_instructor_headers,
    read_cohort,
    read_completion,
    read_session,
    read_trainee,
    record_completion,
    setup_pending_skills_demo,
    setup_session_a_delivered,
    validate_error,
    validate_paginated,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
AUDITOR = TEST_USERS["auditor_headers"]


def _record(api, ctx, trainee_key, session_key, minutes, instructor_key="instructor1"):
    return api.create_module_completion(
        create_module_completion_payload(
            ctx["trainees"][trainee_key]["id"], ctx[session_key]["id"], minutes
        ),
        make_instructor_headers(ctx[instructor_key]["id"]),
    )


# ---------------------------------------------------------------------------
# The attendance floor
# ---------------------------------------------------------------------------

def test_attendance_one_minute_below_the_floor_is_refused(api):
    """PRD §3.4: "Attendance must clear the floor: `attendance_ratio` must be greater than
    or equal to 0.80 — a volunteer who sat exactly four fifths of the class is admitted, and
    anything strictly below that is refused with `ERR_ATTENDANCE_INSUFFICIENT` and HTTP 422."
    PRD §3.4: "The `module_id` is not supplied by the caller; it is copied from the session
    at creation, along with the derived `attendance_ratio`, which is `attendance_minutes`
    divided by the module's `contact_hours` converted to minutes, rounded half-up to four
    decimal places."

    Design: Difficulty/boundary_precision_check/attendance_ratio_exactly_at_minimum_is_accepted
    """
    ctx = setup_session_a_delivered()

    validate_error(
        _record(api, ctx, "tara", "session_a", 119),
        ApiErrorId.ERR_ATTENDANCE_INSUFFICIENT.value,
    )

    _, meta = validate_paginated(
        api.list_module_completions(AUDITOR, {"trainee_id": ctx["trainees"]["tara"]["id"]})
    )
    assert meta["total_count"] == 0, "a refused recording must create no row"
    assert read_session(ctx, "session_a")["recorded_completion_count"] == 0


def test_attendance_exactly_at_the_floor_is_accepted_and_credits_the_module(api):
    """PRD §3.4: "Attendance must clear the floor: `attendance_ratio` must be greater than
    or equal to 0.80 — a volunteer who sat exactly four fifths of the class is admitted, and
    anything strictly below that is refused with `ERR_ATTENDANCE_INSUFFICIENT` and HTTP 422."
    PRD §3.4: "When the module needs no demonstration, the completion advances `RECORDED →
    PASSED` at once and the full passing ledger applies: `credited_contact_hours` is set to
    the module's `contact_hours`; the trainee's `earned_contact_hours` grows by that amount;
    the trainee's `passed_core_count` grows by 1 when the module is core; the trainee's
    `last_qualifying_activity_at` and `readiness_score` are recomputed; and, when the module
    is `refresher_eligible` and the trainee holds a credential standing at `ACTIVE`,
    `GRACE`, `EXPIRED`, or `SUSPENDED`, that credential's `refresher_hours_in_term` grows by
    the credited hours."

    Design: Difficulty/boundary_precision_check/attendance_ratio_exactly_at_minimum_is_accepted
    """
    ctx = setup_session_a_delivered()

    completion = validate_success(_record(api, ctx, "tara", "session_a", 120), 201)
    assert_score(completion["attendance_ratio"], 0.8, "attendance_ratio")
    assert completion["status"] == "PASSED"
    assert_hours(completion["credited_contact_hours"], 2.5, "credited_contact_hours")

    trainee = read_trainee(ctx, "tara")
    assert_hours(trainee["earned_contact_hours"], 2.5, "earned_contact_hours")
    assert trainee["passed_core_count"] == 1

    _, meta = validate_paginated(
        api.list_module_completions(AUDITOR, {"trainee_id": ctx["trainees"]["tara"]["id"]})
    )
    assert meta["total_count"] == 1


# ---------------------------------------------------------------------------
# The completion depends on its session, not on the trainee
# ---------------------------------------------------------------------------

def test_completion_against_a_session_that_was_never_taught_is_refused(api):
    """PRD §3.4: "The referenced session must actually have been taught: a session whose
    status is not `DELIVERED` is refused with `ERR_SESSION_NOT_DELIVERED`."

    Design: Difficulty/cross_entity_state_dependency/completion_requires_its_class_session_to_be_delivered
    """
    ctx = setup_session_a_delivered(deliver=False)
    assert read_session(ctx, "session_a")["status"] == "SCHEDULED"

    validate_error(
        _record(api, ctx, "tara", "session_a", 150),
        ApiErrorId.ERR_SESSION_NOT_DELIVERED.value,
    )
    assert read_session(ctx, "session_a")["recorded_completion_count"] == 0


def test_the_identical_completion_is_accepted_once_the_session_is_delivered(api):
    """PRD §3.4: "The referenced session must actually have been taught: a session whose
    status is not `DELIVERED` is refused with `ERR_SESSION_NOT_DELIVERED`."
    PRD §3.3: "On success, `delivered_at` is stamped from the logical clock and the cohort's
    `delivered_contact_hours` is increased by the module's `contact_hours`."
    PRD §3.3: "New sessions open in `SCHEDULED`, with `delivered_at` null and
    `recorded_completion_count` at 0; that counter tracks how many completions have been
    recorded against the session and excludes any that have been voided."

    Design: Difficulty/cross_entity_state_dependency/completion_requires_its_class_session_to_be_delivered
    """
    ctx = setup_session_a_delivered(deliver=False)
    validate_error(
        _record(api, ctx, "tara", "session_a", 150),
        ApiErrorId.ERR_SESSION_NOT_DELIVERED.value,
    )

    delivered = deliver_session(ctx, "session_a")
    assert delivered["status"] == "DELIVERED"
    assert_instant(delivered["delivered_at"], "2026-08-03T12:00:00Z", "delivered_at")

    completion = validate_success(_record(api, ctx, "tara", "session_a", 150), 201)
    assert completion["status"] == "PASSED"
    assert read_session(ctx, "session_a")["recorded_completion_count"] == 1


# ---------------------------------------------------------------------------
# The bounded retake loop
# ---------------------------------------------------------------------------

def test_a_failed_demonstration_stamps_the_evaluator_but_credits_nothing(api):
    """PRD §3.4: "An `outcome` of `FAIL`, or an `outcome` of `PASS` with a `demo_score`
    strictly below 70, stamps `evaluator_id` and `demo_score` and advances the completion
    `SKILLS_PENDING → FAILED` instead, crediting no hours."
    PRD §3.4: "When the module does require a demonstration, the completion advances
    `RECORDED → SKILLS_PENDING` instead and waits for a signature."

    Design: Difficulty/non_linear_state_machine/skills_demo_retake_loop_is_bounded_and_reopens_pending
    """
    ctx = setup_pending_skills_demo()
    assert read_completion(ctx, "tara_b")["status"] == "SKILLS_PENDING"

    failed = validate_success(
        api.sign_skills_demo(
            ctx["completions"]["tara_b"]["id"], {"outcome": "FAIL", "demo_score": 55},
            make_evaluator_headers(ctx["instructor2"]["id"]),
        )
    )
    assert failed["status"] == "FAILED"
    assert failed["attempt_number"] == 1
    assert failed["demo_score"] == 55

    trainee = read_trainee(ctx, "tara")
    assert_hours(trainee["earned_contact_hours"], 2.5, "earned_contact_hours")
    assert trainee["passed_core_count"] == 1


def test_the_retake_reopens_the_demonstration_and_advances_the_attempt_counter(api):
    """PRD §3.4: "Presenting a demonstration against a completion standing at `FAILED`
    performs a **bounded retake within the same request**: the completion is first reopened
    `FAILED → SKILLS_PENDING`, with `attempt_number` increased by 1 and both `evaluator_id`
    and `demo_score` cleared to null, and the freshly supplied outcome is then evaluated
    against the reopened completion exactly as above, landing it at `PASSED` or back at
    `FAILED`."
    PRD §3.4: "From `SKILLS_PENDING`, an `outcome` of `PASS` accompanied by a `demo_score`
    of at least 70 stamps `evaluator_id` with the acting `X-User-ID`, stamps `demo_score`,
    advances the completion `SKILLS_PENDING → PASSED`, and applies exactly the same passing
    ledger set described above."

    Design: Difficulty/non_linear_state_machine/skills_demo_retake_loop_is_bounded_and_reopens_pending
    """
    ctx = setup_pending_skills_demo()
    evaluator = make_evaluator_headers(ctx["instructor2"]["id"])
    completion_id = ctx["completions"]["tara_b"]["id"]

    validate_success(
        api.sign_skills_demo(completion_id, {"outcome": "FAIL", "demo_score": 55},
                             evaluator)
    )
    retaken = validate_success(
        api.sign_skills_demo(completion_id, {"outcome": "PASS", "demo_score": 91},
                             evaluator)
    )

    assert retaken["status"] == "PASSED"
    assert retaken["attempt_number"] == 2
    assert retaken["demo_score"] == 91
    assert retaken["evaluator_id"] == ctx["instructor2"]["id"]
    assert_hours(retaken["credited_contact_hours"], 2.5, "credited_contact_hours")

    trainee = read_trainee(ctx, "tara")
    assert_hours(trainee["earned_contact_hours"], 5.0, "earned_contact_hours")
    assert trainee["passed_core_count"] == 2


def test_a_fourth_demonstration_attempt_is_refused(api):
    """PRD §3.4: "The retake is permitted only while `attempt_number` is strictly less than
    3; a completion that has already reached the third attempt is refused with
    `ERR_DEMO_ATTEMPTS_EXHAUSTED`."

    Design: Corner/validations/fourth_skills_demonstration_attempt_is_refused
    """
    ctx = setup_pending_skills_demo()
    evaluator = make_evaluator_headers(ctx["instructor2"]["id"])
    completion_id = ctx["completions"]["tara_b"]["id"]

    for score in (40, 50, 60):
        result = validate_success(
            api.sign_skills_demo(completion_id, {"outcome": "FAIL", "demo_score": score},
                                 evaluator)
        )
        assert result["status"] == "FAILED"

    exhausted = read_completion(ctx, "tara_b")
    assert exhausted["attempt_number"] == 3
    assert exhausted["demo_score"] == 60

    validate_error(
        api.sign_skills_demo(completion_id, {"outcome": "PASS", "demo_score": 95},
                             evaluator),
        ApiErrorId.ERR_DEMO_ATTEMPTS_EXHAUSTED.value,
    )

    unchanged = read_completion(ctx, "tara_b")
    assert unchanged["attempt_number"] == 3
    assert unchanged["status"] == "FAILED"
    assert read_trainee(ctx, "tara")["passed_core_count"] == 1


def test_the_delivering_instructor_may_not_sign_their_own_sessions_demonstration(api):
    """PRD §3.4: "The evaluator's `X-User-ID` must differ from the session's
    `instructor_id` on every path through this operation, and a match is refused with
    `ERR_SEGREGATION_OF_DUTIES`."
    PRD §2.7: "The first wall separates teaching from examining: the user signing a skills
    demonstration must not be the instructor who delivered the class session that the
    demonstration belongs to."

    Design: Corner/rbac/evaluator_cannot_sign_a_demonstration_from_the_session_they_delivered
    """
    ctx = setup_pending_skills_demo()
    completion_id = ctx["completions"]["tara_b"]["id"]

    validate_error(
        api.sign_skills_demo(
            completion_id, {"outcome": "PASS", "demo_score": 95},
            make_evaluator_headers(ctx["instructor1"]["id"]),
        ),
        ApiErrorId.ERR_SEGREGATION_OF_DUTIES.value,
    )
    blocked = read_completion(ctx, "tara_b")
    assert blocked["status"] == "SKILLS_PENDING"
    assert blocked["evaluator_id"] is None
    assert blocked["demo_score"] is None

    signed = validate_success(
        api.sign_skills_demo(
            completion_id, {"outcome": "PASS", "demo_score": 95},
            make_evaluator_headers(ctx["instructor2"]["id"]),
        )
    )
    assert signed["status"] == "PASSED"
    assert signed["evaluator_id"] == ctx["instructor2"]["id"]

    trainee = read_trainee(ctx, "tara")
    assert_hours(trainee["earned_contact_hours"], 5.0, "earned_contact_hours")
    assert trainee["passed_core_count"] == 2


# ---------------------------------------------------------------------------
# Curriculum order on the learner, and the one-live-completion rule
# ---------------------------------------------------------------------------

def test_completion_without_a_passed_prerequisite_is_rejected(api):
    """PRD §3.4: "Curriculum order is enforced again, this time on the learner rather than
    the calendar: when the completed module carries a non-null `prerequisite_module_id`, the
    trainee must already hold a completion on that prerequisite standing at `PASSED`,
    otherwise `ERR_PREREQUISITE_NOT_PASSED`."
    PRD §3.4: "When the module does require a demonstration, the completion advances
    `RECORDED → SKILLS_PENDING` instead and waits for a signature."

    Design: Corner/validations/completion_without_a_passed_prerequisite_is_rejected
    """
    ctx = setup_session_a_delivered()
    deliver_session(ctx, "session_b", at="2026-08-04T12:00:00Z")

    validate_error(
        _record(api, ctx, "tara", "session_b", 150),
        ApiErrorId.ERR_PREREQUISITE_NOT_PASSED.value,
    )

    first = validate_success(_record(api, ctx, "tara", "session_a", 150), 201)
    assert first["status"] == "PASSED"

    second = validate_success(_record(api, ctx, "tara", "session_b", 150), 201)
    assert second["status"] == "SKILLS_PENDING"

    trainee = read_trainee(ctx, "tara")
    assert_hours(trainee["earned_contact_hours"], 2.5, "earned_contact_hours")
    assert trainee["passed_core_count"] == 1


def test_a_second_live_completion_for_the_same_module_is_refused(api):
    """PRD §3.4: "And a trainee may hold at most one non-voided completion per module: a
    second live completion for the same trainee and the same module is refused with
    `ERR_DUPLICATE_COMPLETION`, though a previously voided one does not block a fresh
    attempt."

    Design: Corner/validations/second_non_voided_completion_for_the_same_module_is_rejected
    """
    ctx = setup_session_a_delivered()
    first = record_completion(ctx, "tara", "session_a", 150, store_as="tara_a")
    assert first["status"] == "PASSED"

    validate_error(
        _record(api, ctx, "tara", "session_a", 150),
        ApiErrorId.ERR_DUPLICATE_COMPLETION.value,
    )

    validate_success(
        api.void_module_completion(first["id"], {"reason": "Re-keying attendance"}, COORD)
    )
    replacement = validate_success(_record(api, ctx, "tara", "session_a", 140), 201)

    assert read_completion(ctx, "tara_a")["status"] == "VOIDED"
    assert replacement["status"] == "PASSED"
    assert_score(replacement["attendance_ratio"], 0.9333, "attendance_ratio")

    trainee = read_trainee(ctx, "tara")
    assert_hours(trainee["earned_contact_hours"], 2.5, "earned_contact_hours")
    assert trainee["passed_core_count"] == 1


# ---------------------------------------------------------------------------
# Recording and voiding conserve the hour ledger
# ---------------------------------------------------------------------------

def test_recording_a_passing_completion_credits_the_trainee_hour_ledger(api):
    """PRD §3.4: "When the module needs no demonstration, the completion advances `RECORDED
    → PASSED` at once and the full passing ledger applies: `credited_contact_hours` is set
    to the module's `contact_hours`; the trainee's `earned_contact_hours` grows by that
    amount; the trainee's `passed_core_count` grows by 1 when the module is core; the
    trainee's `last_qualifying_activity_at` and `readiness_score` are recomputed; and, when
    the module is `refresher_eligible` and the trainee holds a credential standing at
    `ACTIVE`, `GRACE`, `EXPIRED`, or `SUSPENDED`, that credential's `refresher_hours_in_term`
    grows by the credited hours."

    Design: Difficulty/compensating_invariant/record_then_void_completion_conserves_the_contact_hour_ledger
    """
    ctx = setup_session_a_delivered()
    before = read_trainee(ctx, "tara")
    assert_hours(before["earned_contact_hours"], 0.0, "earned_contact_hours")
    assert before["passed_core_count"] == 0

    completion = record_completion(ctx, "tara", "session_a", 150, store_as="tara_a")
    assert_hours(completion["credited_contact_hours"], 2.5, "credited_contact_hours")

    after = read_trainee(ctx, "tara")
    assert_hours(after["earned_contact_hours"], 2.5, "earned_contact_hours")
    assert after["passed_core_count"] == 1
    assert read_cohort(ctx)["delivered_contact_hours"] == 2.5


def test_voiding_a_passed_completion_returns_the_hour_ledger_without_drift(api):
    """PRD §3.4: "Voiding from `PASSED` fires cascade chain A, six links deep. The
    completion's `credited_contact_hours` drops to 0. Because of that, the trainee's
    `earned_contact_hours` falls by the hours just withdrawn, their `passed_core_count`
    falls by 1 when the module is core, their `readiness_score` is recomputed, and — when
    that leaves `passed_core_count` below the count of curriculum modules that are both core
    and active while the trainee stands at `GRADUATED` — the trainee is demoted `GRADUATED →
    ENROLLED`."
    PRD §3.3: "New sessions open in `SCHEDULED`, with `delivered_at` null and
    `recorded_completion_count` at 0; that counter tracks how many completions have been
    recorded against the session and excludes any that have been voided."

    Design: Difficulty/compensating_invariant/record_then_void_completion_conserves_the_contact_hour_ledger
    """
    ctx = setup_session_a_delivered()
    completion = record_completion(ctx, "tara", "session_a", 150, store_as="tara_a")

    voided = validate_success(
        api.void_module_completion(
            completion["id"], {"reason": "Duplicate roster entry"}, COORD
        )
    )
    assert voided["status"] == "VOIDED"
    assert_hours(voided["credited_contact_hours"], 0.0, "credited_contact_hours")

    trainee = read_trainee(ctx, "tara")
    assert_hours(trainee["earned_contact_hours"], 0.0, "earned_contact_hours")
    assert trainee["passed_core_count"] == 0
    assert_score(trainee["readiness_score"], 0.0, "readiness_score")

    assert read_cohort(ctx)["delivered_contact_hours"] == 2.5, (
        "the session itself is still delivered, so the cohort hours are untouched"
    )
    session = read_session(ctx, "session_a")
    assert session["status"] == "DELIVERED"
    assert session["recorded_completion_count"] == 0
