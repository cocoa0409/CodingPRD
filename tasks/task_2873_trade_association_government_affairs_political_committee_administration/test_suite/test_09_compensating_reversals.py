"""Compensating voids restore every accumulator term, not merely the total."""
from test_helpers import (
    DEFAULT_CLOCK_INSTANT,
    DIRECTOR,
    api_client,
    assert_candidate_accumulator_split,
    assert_fund_terms,
    assert_instant_equals,
    propose_contribution,
    read_activity,
    read_candidate,
    read_contribution,
    read_fund,
    read_registration,
    read_report,
    setup_disbursed_contribution,
    setup_open_report_with_activities,
    validate_error,
    void_activity,
    void_contribution,
    void_payload,
)

RETURNED_CHECK = "Check returned by the campaign committee"

DISBURSED_SETUP = dict(
    amount_cents=250_000,
    min_reserve_cents=0,
    receipt_amount_cents=300_000,
)

ACTIVITY_A1 = {"activity_date": "2026-07-05", "hours": 3.333, "expenditure_cents": 400_000}
ACTIVITY_A2 = {"activity_date": "2026-07-06", "hours": 2.667, "expenditure_cents": 300_000}
DOUBLE_BOOKED = "Double-booked consultant hours removed after review"


def test_voiding_a_disbursed_contribution_restores_every_fund_term():
    """A returned check unwinds the fund and the candidate term by term.

    PRD 3.9: "From `DISBURSED` — a returned check: the fund's
    `disbursed_total_cents` falls by `amount_cents`, `available_balance_cents` is
    recomputed upward, and the candidate's `disbursed_support_cents` falls by the
    amount."
    PRD 3.9: "Restoring the grand total while leaving an individual term wrong is a
    failure, not a rounding difference."

    Design: Difficulty/compensating_invariant/void_disbursed_contribution_restores_fund_conservation_identity
    """
    state = setup_disbursed_contribution(**DISBURSED_SETUP)
    fund_id = state["fund"]["id"]
    candidate_id = state["candidate"]["id"]
    contribution_id = state["contribution"]["id"]

    assert_fund_terms(
        read_fund(fund_id),
        receipts=300_000,
        committed=0,
        disbursed=250_000,
        fees=0,
        available=50_000,
        posture="OPEN",
    )
    assert_candidate_accumulator_split(
        read_candidate(candidate_id), pending=0, committed=0, disbursed=250_000
    )

    voided = void_contribution(contribution_id, RETURNED_CHECK)
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == RETURNED_CHECK
    assert_instant_equals(voided["voided_at"], DEFAULT_CLOCK_INSTANT, "voided_at")

    assert_fund_terms(
        read_fund(fund_id),
        receipts=300_000,
        committed=0,
        disbursed=0,
        fees=0,
        available=300_000,
        posture="OPEN",
    )
    assert_candidate_accumulator_split(
        read_candidate(candidate_id), pending=0, committed=0, disbursed=0
    )


def test_the_void_re_opens_the_full_per_candidate_headroom():
    """A voided row leaves the already-absorbed sum, so the ceiling comes back.

    PRD 3.9: "Voided contributions are excluded from that sum, which is precisely
    why a void frees headroom again."
    PRD 3.9: "`max_allowed_cents` is then the smaller of the tier allowance and the
    remaining room."

    Design: Difficulty/compensating_invariant/void_disbursed_contribution_restores_fund_conservation_identity
    """
    state = setup_disbursed_contribution(**DISBURSED_SETUP)
    fund_id = state["fund"]["id"]
    candidate_id = state["candidate"]["id"]
    assert state["contribution"]["max_allowed_cents"] == 250_000

    void_contribution(state["contribution"]["id"], RETURNED_CHECK)

    reissued = propose_contribution(
        fund_id,
        candidate_id,
        amount_cents=250_000,
        memo="Re-issued after the returned check",
    )
    assert reissued["max_allowed_cents"] == 250_000
    assert reissued["status"] == "PENDING_BOARD"
    assert reissued["amount_cents"] == 250_000

    assert_candidate_accumulator_split(
        read_candidate(candidate_id), pending=250_000, committed=0, disbursed=0
    )
    assert read_contribution(state["contribution"]["id"])["status"] == "VOIDED"


def test_voiding_one_activity_restores_the_registration_accumulators_exactly():
    """The void subtracts this activity's own cents and its own hours.

    PRD 3.5: "When the void proceeds it compensates exactly what the log added: the
    activity's `expenditure_cents` is subtracted from `ytd_reportable_cents` and its
    `hours` from `ytd_reportable_hours`, the registration's `version` increments, and
    every `OPEN` report that included the activity recomputes
    `method_a_total_cents`, `method_b_total_cents`, `filed_total_cents` and
    `included_activity_count`."
    PRD 2.7: "a voided activity must remove exactly its own expenditure and exactly
    its own hours from its registration's accumulators."

    Design: Difficulty/compensating_invariant/void_activity_restores_registration_accumulators_and_open_report_totals
    """
    state = setup_open_report_with_activities(
        [ACTIVITY_A1, ACTIVITY_A2], period_code="2026Q3", basis="METHOD_B"
    )
    registration_id = state["registration"]["id"]
    activity_1, activity_2 = state["activities"]

    before = read_registration(registration_id)
    assert before["ytd_reportable_cents"] == 700_000
    assert float(before["ytd_reportable_hours"]) == 6.000
    assert before["status"] == "ACTIVE"

    voided = void_activity(activity_2["id"], DOUBLE_BOOKED)
    assert voided["status"] == "VOIDED"
    assert voided["void_reason"] == DOUBLE_BOOKED

    after = read_registration(registration_id)
    assert after["ytd_reportable_cents"] == 400_000
    assert float(after["ytd_reportable_hours"]) == 3.333
    assert after["status"] == "ACTIVE"
    assert after["amendment_round"] == 0
    assert after["version"] > before["version"]

    survivor = read_activity(registration_id, activity_1["id"])
    assert survivor["status"] == "LOGGED"
    assert survivor["staff_cost_cents"] == 28_331
    assert survivor["void_reason"] is None


def test_the_open_report_recomputes_per_activity_and_cannot_be_compensated_twice():
    """The report drops exactly this activity's rounded share, and only once.

    PRD 3.5: "Reports that are `CERTIFIED` or `SUPERSEDED` are never recomputed by a
    void."
    PRD 3.5: "an already-voided activity gives `ERR_ACTIVITY_ALREADY_VOIDED`."

    Design: Difficulty/compensating_invariant/void_activity_restores_registration_accumulators_and_open_report_totals
    """
    state = setup_open_report_with_activities(
        [ACTIVITY_A1, ACTIVITY_A2], period_code="2026Q3", basis="METHOD_B"
    )
    registration_id = state["registration"]["id"]
    report_id = state["report"]["id"]
    activity_2 = state["activities"][1]

    before = read_report(registration_id, report_id)
    assert before["method_a_total_cents"] == 700_000
    assert before["method_b_total_cents"] == 751_001
    assert before["filed_total_cents"] == 751_001
    assert before["included_activity_count"] == 2

    void_activity(activity_2["id"], DOUBLE_BOOKED)

    after = read_report(registration_id, report_id)
    assert after["method_a_total_cents"] == 400_000
    assert after["method_b_total_cents"] == 428_331
    assert after["filed_total_cents"] == 428_331
    assert after["included_activity_count"] == 1
    assert after["status"] == "OPEN"

    replay = api_client.void_lobbying_activity(
        activity_2["id"], void_payload(DOUBLE_BOOKED), DIRECTOR
    )
    validate_error(replay, "ERR_ACTIVITY_ALREADY_VOIDED", 409)

    unchanged = read_report(registration_id, report_id)
    assert unchanged["method_b_total_cents"] == 428_331
    assert unchanged["included_activity_count"] == 1
