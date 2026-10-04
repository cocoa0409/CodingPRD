"""Difficulty queue — boundary precision and cross-entity state dependencies.

Scaled-score equality at the ratified mark and the exact registration deadline
(PRD §3.3); registration gated on window state and attempts gated on enrollment
state (PRD §3.3, §3.5).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_AT_DEADLINE,
    CLOCK_BEFORE_DEADLINE_1S,
    CLOCK_SCORING,
    FEE_LATE_CENTS,
    MODULE_M1_CODE,
    MODULE_M1_TITLE,
    MODULE_PASSING_SCORE,
    PASS_MARK_RATIFIED,
    RAW_SCORE_AT_MARK,
    RAW_SCORE_BELOW_MARK,
    REGISTRAR,
    SCALED_AT_MARK,
    SCALED_BELOW_MARK,
    SEVERITY_MAX,
    TRACK_QFI,
    create_exam_registration_payload,
    create_module_attempt_payload,
    expel_candidate,
    get_enrollment,
    get_candidate,
    get_success_data,
    make_active_exam,
    make_candidate,
    make_candidate_headers,
    make_module,
    make_window,
    propose_ratify_publish,
    record_score,
    register,
    set_clock,
    setup_associate,
    setup_enrollment,
    setup_open_window,
    setup_registered,
    validate_error,
)


def _two_scored_candidates(api):
    """Two SAT registrations with raw 39 (scaled 6.5) and raw 38 (scaled 6.3);
    pass mark ratified at 6.5 and published."""
    ctx = setup_registered(api, num_candidates=2)
    window = ctx["window"]
    reg1, reg2 = ctx["registrations"]
    set_clock(api, CLOCK_SCORING)
    scored1 = record_score(api, reg1["id"], RAW_SCORE_AT_MARK)
    scored2 = record_score(api, reg2["id"], RAW_SCORE_BELOW_MARK)
    propose_ratify_publish(api, window["id"], proposed_mark=PASS_MARK_RATIFIED,
                           ratified_mark=PASS_MARK_RATIFIED)
    rows = get_success_data(api.list_window_registrations(window["id"], REGISTRAR))
    return {"scored1": scored1, "scored2": scored2, "rows": rows,
            "reg1": reg1, "reg2": reg2}


def test_scaled_score_equal_to_mark_passes(api):
    """PRD §3.3: "its official `result` is set to `PASS` when its
    `scaled_score` is at least the `ratified_mark` (equality passes) and to
    `FAIL` otherwise."

    Design: Difficulty/boundary_precision_check/scaled_score_exactly_at_pass_mark_passes
    """
    sc = _two_scored_candidates(api)
    assert sc["scored1"]["scaled_score"] == pytest.approx(SCALED_AT_MARK, abs=1e-6)
    row1 = [r for r in sc["rows"] if r["id"] == sc["reg1"]["id"]][0]
    # scaled 6.5 == ratified 6.5: the equality boundary passes.
    assert row1["result"] == "PASS"
    assert row1["grading_status"] == "RELEASED"


def test_scaled_score_one_raw_point_below_mark_fails(api):
    """PRD §3.3: "its official `result` is set to `PASS` when its
    `scaled_score` is at least the `ratified_mark` (equality passes) and to
    `FAIL` otherwise."
    PRD §3.3: "The `scaled_score` is then derived: the raw score is divided by
    sixty, multiplied by ten, and rounded half-up to one decimal place."

    Design: Difficulty/boundary_precision_check/scaled_score_exactly_at_pass_mark_passes
    """
    sc = _two_scored_candidates(api)
    # raw 38 -> round_half_up(38/60*10, 1) == 6.3, one raw point below.
    assert sc["scored2"]["scaled_score"] == pytest.approx(SCALED_BELOW_MARK, abs=1e-6)
    row2 = [r for r in sc["rows"] if r["id"] == sc["reg2"]["id"]][0]
    assert row2["result"] == "FAIL"
    assert row2["grading_status"] == "RELEASED"


def test_registration_one_second_before_deadline_succeeds(api):
    """PRD §3.3: "A `SCHEDULED` window becomes `REGISTRATION_OPEN` once the
    clock reaches `registration_opens_at`, becomes `REGISTRATION_CLOSED` once
    the clock reaches `registration_deadline`."

    Design: Difficulty/boundary_precision_check/registration_at_exact_deadline_rejected
    """
    ctx = setup_open_window(api)
    candidate = make_candidate(api)
    set_clock(api, CLOCK_BEFORE_DEADLINE_1S)
    registration = register(api, ctx["window"]["id"], candidate)
    assert registration["logistics_status"] == "REGISTERED"
    # One second before the deadline is inside the late tier:
    # 37500 + round_half_up(37500 * 0.015) = 37500 + 563.
    assert registration["fee_charged_cents"] == FEE_LATE_CENTS


def test_registration_at_exact_deadline_rejected(api):
    """PRD §3.3: "Because the sweep closes registration the instant the clock
    reaches the deadline, a registration attempted at exactly the
    `registration_deadline` is already too late and is rejected as if the
    deadline had passed."

    Design: Difficulty/boundary_precision_check/registration_at_exact_deadline_rejected
    """
    ctx = setup_open_window(api)
    candidate = make_candidate(api)
    set_clock(api, CLOCK_AT_DEADLINE)
    resp = api.create_exam_registration(
        create_exam_registration_payload(ctx["window"]["id"]),
        make_candidate_headers(candidate["id"]))
    validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_OPEN)


def test_registration_rejected_while_window_scheduled(api):
    """PRD §3.3: "The window must be `REGISTRATION_OPEN` — a registration
    against a window in any other status, including the exact-deadline
    boundary above, is rejected with `ERR_WINDOW_NOT_OPEN`."

    Design: Difficulty/cross_entity_state_dependency/registration_requires_window_open
    """
    _, exam = make_active_exam(api)
    window = make_window(api, exam["id"], window_code="P-2026-11",
                         registration_opens_at="2026-09-10T00:00:00Z")
    candidate = make_candidate(api)
    # No clock-set call has run: the window is still SCHEDULED.
    assert window["status"] == "SCHEDULED"
    resp = api.create_exam_registration(
        create_exam_registration_payload(window["id"]),
        make_candidate_headers(candidate["id"]))
    validate_error(resp, ApiErrorId.ERR_WINDOW_NOT_OPEN)


def test_registration_accepted_once_window_opens(api):
    """PRD §3.3: "A `SCHEDULED` window becomes `REGISTRATION_OPEN` once the
    clock reaches `registration_opens_at`."

    Design: Difficulty/cross_entity_state_dependency/registration_requires_window_open
    """
    _, exam = make_active_exam(api)
    window = make_window(api, exam["id"], window_code="P-2026-11",
                         registration_opens_at="2026-09-10T00:00:00Z")
    candidate = make_candidate(api)
    set_clock(api, "2026-09-10T00:00:00Z")
    registration = register(api, window["id"], candidate)
    assert registration["logistics_status"] == "REGISTERED"
    assert registration["grading_status"] == "PENDING"


def _expelled_with_enrollment(api):
    candidate = setup_associate(api)["candidate"]
    enrollment = setup_enrollment(api, candidate, with_modules=False)["enrollment"]
    module = make_module(api, module_code=MODULE_M1_CODE, track_code=TRACK_QFI,
                         sequence_index=1, title=MODULE_M1_TITLE,
                         passing_score=MODULE_PASSING_SCORE)
    expel_candidate(api, candidate["id"], charge="Serious misconduct",
                    severity=SEVERITY_MAX)
    return {"candidate": candidate, "enrollment": enrollment, "module": module}


def test_expulsion_withdraws_enrollment(api):
    """PRD §3.9: "The candidate's `status` becomes `EXPELLED` — from which
    there is no return."
    PRD §3.9: "And the candidate's track enrollment in `ENROLLED` or
    `CAPSTONE_ELIGIBLE` is withdrawn to `WITHDRAWN`."

    Design: Difficulty/cross_entity_state_dependency/module_attempt_requires_active_enrollment
    """
    sc = _expelled_with_enrollment(api)
    candidate = get_candidate(api, sc["candidate"]["id"])
    assert candidate["status"] == "EXPELLED"
    enrollment = get_enrollment(api, sc["candidate"])
    assert enrollment["status"] == "WITHDRAWN"


def test_attempt_on_withdrawn_enrollment_rejected(api):
    """PRD §3.5: "The enrollment must be `ENROLLED` or `CAPSTONE_ELIGIBLE`; an
    attempt under any other enrollment status is rejected with
    `ERR_ENROLLMENT_NOT_ACTIVE`."

    Design: Difficulty/cross_entity_state_dependency/module_attempt_requires_active_enrollment
    """
    sc = _expelled_with_enrollment(api)
    resp = api.create_module_attempt(
        create_module_attempt_payload(sc["enrollment"]["id"], sc["module"]["id"]),
        make_candidate_headers(sc["candidate"]["id"]))
    validate_error(resp, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE)
