"""Corner queue — calculation rules not owned by the difficulty index.

Scaled-score rounding (PRD §3.3), the half-refund rule with promotion
suppressed (PRD §3.3), transition-credit mapping across syllabus retirement
(PRD §2.10, §3.1), and waitlist promotion order (PRD §3.3).
"""
import pytest

from test_helpers import (
    ApiErrorId,
    CLOCK_FM2_WINDOW_OPEN,
    CLOCK_REGISTRATION_CLOSED,
    CLOCK_REGISTRATION_OPEN,
    CLOCK_SCORING,
    FEE_EARLY_CENTS,
    FM2_REGISTRATION_DEADLINE,
    FM2_REGISTRATION_OPENS,
    FM2_TESTING_ENDS,
    FM2_TESTING_STARTS,
    FM2_WINDOW_CODE,
    RAW_SCORE_AT_MARK,
    RAW_SCORE_HALF_UP,
    RAW_SCORE_TRUNCATING,
    REFUND_HALF_OF_EARLY_CENTS,
    REGISTRAR,
    SCALED_HALF_UP,
    SCALED_TRUNCATING,
    SECOND_SYLLABUS_CODE,
    STANDARD_SYLLABUS_CODE,
    WINDOW_CAPACITY_TIGHT,
    activate_syllabus,
    cancel_registration,
    create_exam_registration_payload,
    get_candidate,
    get_success_data,
    get_window,
    make_candidate,
    make_candidate_headers,
    make_exam,
    make_syllabus,
    make_window,
    propose_ratify_publish,
    record_score,
    register,
    set_clock,
    setup_registered,
    validate_error,
)


def test_scaled_score_rounding_half_up(api):
    """PRD §3.3: "The `scaled_score` is then derived: the raw score is divided
    by sixty, multiplied by ten, and rounded half-up to one decimal place; it
    remains null until a raw score exists."
    PRD §2.7: "Scaled examination scores are kept to exactly one decimal place
    using the standard round-half-up method."

    Design: Corner/calculations/scaled_score_rounding_half_up
    """
    ctx = setup_registered(api, num_candidates=2)
    reg1, reg2 = ctx["registrations"]
    # New rows: no raw score yet, so the scaled score is null.
    assert reg1["scaled_score"] is None
    set_clock(api, CLOCK_SCORING)
    scored1 = record_score(api, reg1["id"], RAW_SCORE_HALF_UP)
    scored2 = record_score(api, reg2["id"], RAW_SCORE_TRUNCATING)
    # 33/60*10 == 5.5 exactly; 32/60*10 == 5.333... -> 5.3.
    assert scored1["scaled_score"] == pytest.approx(SCALED_HALF_UP, abs=1e-6)
    assert scored2["scaled_score"] == pytest.approx(SCALED_TRUNCATING, abs=1e-6)


def test_cancel_after_deadline_half_refund_no_promotion(api):
    """PRD §3.3: "cancelling at or after the deadline — which, given the
    window states above, means while the window is `REGISTRATION_CLOSED` —
    refunds half of the fee, rounded half-up to a whole cent."
    PRD §3.3: "if the window is still `REGISTRATION_OPEN` that freed seat
    immediately promotes a waitlisted registration."

    Design: Corner/calculations/cancel_after_deadline_half_refund_no_promotion
    """
    ctx = setup_registered(api, num_candidates=2, capacity=WINDOW_CAPACITY_TIGHT)
    cand_a, cand_b = ctx["candidates"]
    reg_a, reg_b = ctx["registrations"]
    assert reg_b["logistics_status"] == "WAITLISTED"
    set_clock(api, CLOCK_REGISTRATION_CLOSED)

    cancelled = cancel_registration(api, reg_a["id"], make_candidate_headers(cand_a["id"]))
    assert cancelled["logistics_status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "CANDIDATE"
    # round_half_up(30450 * 0.5) == 15225.
    assert cancelled["refund_cents"] == REFUND_HALF_OF_EARLY_CENTS

    window = get_window(api, ctx["window"]["id"])
    assert window["status"] == "REGISTRATION_CLOSED"
    assert window["seats_held"] == 0
    assert window["waitlist_count"] == 1
    row_b = get_success_data(api.list_candidate_registrations(cand_b["id"], REGISTRAR))[0]
    # Promotion requires REGISTRATION_OPEN: the waitlisted row stays put.
    assert row_b["logistics_status"] == "WAITLISTED"
    assert row_b["fee_charged_cents"] is None


def test_credit_hours_transition_mapping_prereq(api):
    """PRD §2.10: "A `PASS` credit earned on an exam whose version later
    retires confers credit on the mapped exam of the version whose activation
    retired it, whenever such a mapping key exists; an unmapped credit remains
    a historical credit on the original exam, still counting toward credit
    totals but satisfying only that exam's own prerequisite."
    PRD §3.1: "`earned_exam_credit_hours` sums the `credit_hours` of the
    distinct exams on which the candidate holds a `PASS` credit, with a pass
    earned on a `RETIRED` exam counting toward its mapped `ACTIVE` exam per
    the transition-credit mapping and never counted twice."

    Design: Corner/calculations/credit_hours_transition_mapping_prereq
    """
    syl1 = make_syllabus(api, version_code=STANDARD_SYLLABUS_CODE)
    exam_p = make_exam(api, syl1["id"], exam_code="P", title="Probability")
    make_exam(api, syl1["id"], exam_code="FM", title="Financial Mathematics",
              prerequisite_exam_id=exam_p["id"])
    activate_syllabus(api, syl1["id"])
    win_p = make_window(api, exam_p["id"], window_code="P-2026-10")
    cand1 = make_candidate(api)
    cand2 = make_candidate(api)
    set_clock(api, CLOCK_REGISTRATION_OPEN)
    reg1 = register(api, win_p["id"], cand1)
    set_clock(api, CLOCK_SCORING)
    record_score(api, reg1["id"], RAW_SCORE_AT_MARK)
    propose_ratify_publish(api, win_p["id"])

    syl2 = make_syllabus(api, version_code=SECOND_SYLLABUS_CODE,
                         credit_map={"P": "P2", "FM": "FM2"})
    exam_p2 = make_exam(api, syl2["id"], exam_code="P2", title="Probability (2026)")
    exam_fm2 = make_exam(api, syl2["id"], exam_code="FM2",
                         title="Financial Mathematics (2026)",
                         prerequisite_exam_id=exam_p2["id"])
    activate_syllabus(api, syl2["id"])
    win_fm2 = make_window(api, exam_fm2["id"], window_code=FM2_WINDOW_CODE,
                          registration_opens_at=FM2_REGISTRATION_OPENS,
                          registration_deadline=FM2_REGISTRATION_DEADLINE,
                          testing_starts_at=FM2_TESTING_STARTS,
                          testing_ends_at=FM2_TESTING_ENDS)
    set_clock(api, CLOCK_FM2_WINDOW_OPEN)

    # cand2 holds no credits: FM2's prerequisite on P2 is unmet.
    resp = api.create_exam_registration(
        create_exam_registration_payload(win_fm2["id"]),
        make_candidate_headers(cand2["id"]))
    validate_error(resp, ApiErrorId.ERR_PREREQUISITE_NOT_MET)

    # cand1's retired-P credit maps onto P2 and satisfies the prerequisite.
    registered = register(api, win_fm2["id"], cand1)
    assert registered["logistics_status"] == "REGISTERED"

    refreshed = get_candidate(api, cand1["id"])
    # The mapped credit is counted once: 10 hours, not 20.
    assert refreshed["earned_exam_credit_hours"] == 10


def test_waitlist_promotion_order_created_at(api):
    """PRD §3.3: "Waitlist promotion draws only from the window's own
    `WAITLISTED` rows, promoting the earliest-created one — ties broken by the
    promoting candidate records' own `created_at` in ascending order, never by
    identifier — and when no row is waiting the promotion is a no-op."

    Design: Corner/calculations/waitlist_promotion_order_created_at
    """
    ctx = setup_registered(api, num_candidates=3, capacity=WINDOW_CAPACITY_TIGHT)
    cand_a = ctx["candidates"][0]
    reg_a, reg_b, reg_c = ctx["registrations"]
    assert reg_b["logistics_status"] == "WAITLISTED"
    assert reg_c["logistics_status"] == "WAITLISTED"

    cancel_registration(api, reg_a["id"], make_candidate_headers(cand_a["id"]))

    rows = get_success_data(api.list_window_registrations(ctx["window"]["id"], REGISTRAR))
    by_id = {r["id"]: r for r in rows}
    assert by_id[reg_a["id"]]["logistics_status"] == "CANCELLED"
    # candB's row was created before candC's: the earliest waiting row is promoted.
    assert by_id[reg_b["id"]]["logistics_status"] == "REGISTERED"
    assert by_id[reg_b["id"]]["fee_charged_cents"] == FEE_EARLY_CENTS
    assert by_id[reg_c["id"]]["logistics_status"] == "WAITLISTED"
