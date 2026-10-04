"""Difficulty queue — validation priority conflicts.

The fixed priority order of PRD §2.8 decides which violation is reported when
one request breaks two rules from different categories.
"""
from test_helpers import (
    ApiErrorId,
    CLOCK_COOLDOWN_EXACT,
    CLOCK_FM2_WINDOW_OPEN,
    CLOCK_SUSPENDED_ATTEMPT,
    DEFAULT_COOLDOWN_DAYS,
    FM2_REGISTRATION_DEADLINE,
    FM2_REGISTRATION_OPENS,
    FM2_TESTING_ENDS,
    FM2_TESTING_STARTS,
    FM2_WINDOW_CODE,
    MODULE_M1_CODE,
    MODULE_M1_TITLE,
    MODULE_PASSING_SCORE,
    SECOND_SYLLABUS_CODE,
    STANDARD_SYLLABUS_CODE,
    SUBMIT_SCORE_FAIL,
    SUSPENSION_DAYS,
    TRACK_QFI,
    activate_syllabus,
    attempt_and_submit,
    create_exam_registration_payload,
    create_module_attempt_payload,
    make_candidate,
    make_candidate_headers,
    make_exam,
    make_module,
    make_syllabus,
    make_window,
    set_clock,
    setup_associate,
    setup_enrollment,
    suspend_candidate,
    validate_error,
)


def _two_version_catalogue(api):
    """v1 with exams P and FM (FM prereq P) plus an FM window; v2 activated
    with credit_map {P: P2, FM: FM2} so the v1 windows cancel."""
    syl1 = make_syllabus(api, version_code=STANDARD_SYLLABUS_CODE)
    exam_p = make_exam(api, syl1["id"], exam_code="P", title="Probability")
    exam_fm = make_exam(api, syl1["id"], exam_code="FM", title="Financial Mathematics",
                        prerequisite_exam_id=exam_p["id"])
    activate_syllabus(api, syl1["id"])
    win_p = make_window(api, exam_p["id"], window_code="P-2026-10")
    win_fm = make_window(api, exam_fm["id"], window_code="FM-2026-10")
    syl2 = make_syllabus(api, version_code=SECOND_SYLLABUS_CODE,
                         credit_map={"P": "P2", "FM": "FM2"})
    exam_p2 = make_exam(api, syl2["id"], exam_code="P2", title="Probability (2026)")
    exam_fm2 = make_exam(api, syl2["id"], exam_code="FM2",
                         title="Financial Mathematics (2026)",
                         prerequisite_exam_id=exam_p2["id"])
    activate_syllabus(api, syl2["id"])
    return {"exam_p": exam_p, "exam_fm2": exam_fm2, "win_p": win_p, "win_fm": win_fm}


def test_cancelled_window_registration_reports_state_error(api):
    """PRD §2.8: "8. **State preconditions.** Target and parent states must
    admit the operation — the state-guard errors of §3, all HTTP 422."
    PRD §2.8: "10. **Uniqueness and progression gates.** Duplicate active
    registrations, duplicate credited VEE topics, duplicate active
    enrollments, and duplicate cycle attestations are conflicts (HTTP 409);
    prerequisite, sequencing, stage, and segregation gates are unprocessable
    (HTTP 422)."
    The candidate also lacks the FM prerequisite credit; the state-guard error
    is the one reported.

    Design: Difficulty/priority_pair_validation_conflict/registration_state_beats_constraint
    """
    sc = _two_version_catalogue(api)
    candidate = make_candidate(api)
    resp = api.create_exam_registration(
        create_exam_registration_payload(sc["win_fm"]["id"]),
        make_candidate_headers(candidate["id"]))
    validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_OPEN)


def test_state_and_prerequisite_errors_in_isolation(api):
    """PRD §3.3: "The window must be `REGISTRATION_OPEN` — a registration
    against a window in any other status, including the exact-deadline
    boundary above, is rejected with `ERR_WINDOW_NOT_OPEN`."
    PRD §3.3: "When the exam declares a `prerequisite_exam_id`, the candidate
    must already hold credit on that prerequisite — either a direct `PASS` or
    a mapped credit through transition mapping — else the registration is
    rejected with `ERR_PREREQUISITE_NOT_MET`."

    Design: Difficulty/priority_pair_validation_conflict/registration_state_beats_constraint
    """
    sc = _two_version_catalogue(api)
    candidate = make_candidate(api)
    headers = make_candidate_headers(candidate["id"])
    # State violation alone: exam P declares no prerequisite, its window was
    # cancelled by the retirement cascade.
    resp_state = api.create_exam_registration(
        create_exam_registration_payload(sc["win_p"]["id"]), headers)
    validate_error(resp_state, ApiErrorId.ERR_WINDOW_NOT_OPEN)
    # Constraint violation alone: the FM2 window is open but the candidate
    # holds no P2 credit.
    win_fm2 = make_window(api, sc["exam_fm2"]["id"], window_code=FM2_WINDOW_CODE,
                          registration_opens_at=FM2_REGISTRATION_OPENS,
                          registration_deadline=FM2_REGISTRATION_DEADLINE,
                          testing_starts_at=FM2_TESTING_STARTS,
                          testing_ends_at=FM2_TESTING_ENDS)
    set_clock(api, CLOCK_FM2_WINDOW_OPEN)
    resp_constraint = api.create_exam_registration(
        create_exam_registration_payload(win_fm2["id"]), headers)
    validate_error(resp_constraint, ApiErrorId.ERR_PREREQUISITE_NOT_MET)


def _suspended_in_cooldown_scenario(api):
    """ASSOCIATE candidate with a FAILED module attempt (cooldown running) who
    is then SUSPENDED for 30 days."""
    candidate = setup_associate(api)["candidate"]
    enrollment = setup_enrollment(api, candidate, with_modules=False)["enrollment"]
    module = make_module(api, module_code=MODULE_M1_CODE, track_code=TRACK_QFI,
                         sequence_index=1, title=MODULE_M1_TITLE,
                         passing_score=MODULE_PASSING_SCORE,
                         cooldown_days=DEFAULT_COOLDOWN_DAYS)
    failed = attempt_and_submit(api, candidate, enrollment, module, score=SUBMIT_SCORE_FAIL)
    assert failed["status"] == "FAILED"
    set_clock(api, CLOCK_SUSPENDED_ATTEMPT)
    suspend_candidate(api, candidate["id"], suspension_days=SUSPENSION_DAYS)
    return {"candidate": candidate, "enrollment": enrollment, "module": module}


def test_suspended_candidate_attempt_reports_standing_error(api):
    """PRD §2.8: "9. **Candidate standing.** Candidate-initiated writes and
    discipline sanctions require the candidate to be `ACTIVE` — violations
    yield `ERR_CANDIDATE_NOT_ACTIVE`."
    PRD §2.8: "11. **Temporal windows.** The module retake cooldown and session
    bookability are unprocessable (HTTP 422); window schedule conflicts and
    same-calendar-day attendance conflicts are conflicts (HTTP 409)."
    The retake cooldown is also still running; the standing error is the one
    reported.

    Design: Difficulty/priority_pair_validation_conflict/module_attempt_safety_beats_temporal
    """
    sc = _suspended_in_cooldown_scenario(api)
    resp = api.create_module_attempt(
        create_module_attempt_payload(sc["enrollment"]["id"], sc["module"]["id"]),
        make_candidate_headers(sc["candidate"]["id"]))
    validate_error(resp, ApiErrorId.ERR_CANDIDATE_NOT_ACTIVE)


def test_suspended_candidate_attempt_after_cooldown_still_standing_error(api):
    """PRD §2.9: "Standing gates nearly every candidate-initiated write in the
    system: only an `ACTIVE` candidate may ... start a module attempt ...;
    every one of these attempts by a non-`ACTIVE` candidate is rejected with
    `ERR_CANDIDATE_NOT_ACTIVE`."
    The clock has reached submitted_at + cooldown_days (cooldown no longer
    blocks) while the 30-day suspension is still running, isolating the
    standing violation.

    Design: Difficulty/priority_pair_validation_conflict/module_attempt_safety_beats_temporal
    """
    sc = _suspended_in_cooldown_scenario(api)
    set_clock(api, CLOCK_COOLDOWN_EXACT)
    resp = api.create_module_attempt(
        create_module_attempt_payload(sc["enrollment"]["id"], sc["module"]["id"]),
        make_candidate_headers(sc["candidate"]["id"]))
    validate_error(resp, ApiErrorId.ERR_CANDIDATE_NOT_ACTIVE)
