"""Formulas assembled from several independent inputs: the candidate support
score, the filing-cycle fee, and the per-activity staff-cost rounding."""
from test_helpers import (
    assert_fund_invariants,
    assert_pac_contribution,
)
from test_helpers.fixtures import (
    open_fund,
    propose_contribution,
    read_activity,
    read_candidate,
    read_fund,
    read_registration,
    register_candidate,
    run_filing_cycle,
    setup_funded_fund,
    setup_live_campaign,
    setup_open_report_with_activities,
)

CHALLENGER = {
    "name": "Alex Rivera",
    "incumbency": "CHALLENGER",
    "voting_alignment_pct": 78.40,
    "committee_relevance_score": 62,
    "district_code": "CA-12",
}
# 0.45 x 78.40 + 0.25 x 62 + 0.20 x 60 + 0.10 x 30 = 65.78
SCORE_WITH_ENGAGEMENT = 65.78
# The same candidate in a district no alert reached: the last term drops out.
SCORE_WITHOUT_ENGAGEMENT = 62.78


def test_support_score_blends_alignment_relevance_incumbency_and_engagement():
    """All four weighted components land in one score, rounded once at the end.

    PRD 3.9: "The score is then forty-five hundredths of `voting_alignment_pct`,
    plus twenty-five hundredths of `committee_relevance_score`, plus twenty
    hundredths of an incumbency factor of 100 for an `INCUMBENT`, 60 for a
    `CHALLENGER` or 80 for an `OPEN_SEAT`, plus ten hundredths of the district
    engagement; that assembled sum is rounded half up to two decimals exactly
    once, at the end."
    PRD 3.9: "count the total `matched_member_count` across every action alert in
    the system whose `status` is `DISPATCHED` and whose `target_district_code`
    equals this candidate's `district_code` — alerts that resolved to `NO_MATCH`
    contribute nothing — then multiply that count by 10 and cap the result at
    100."

    Design: Difficulty/combinatorial_formula/candidate_support_score_four_input_nonlinear_blend
    """
    live = setup_live_campaign()
    assert live["alert"]["status"] == "DISPATCHED"
    assert live["alert"]["matched_member_count"] == 3
    assert live["alert"]["cost_cents"] == 90_000

    fund = open_fund()
    candidate = register_candidate(**CHALLENGER)
    contribution = propose_contribution(
        fund["id"], candidate["id"], amount_cents=100_000,
        memo="Quarter-share support for a well aligned challenger",
    )

    assert_pac_contribution(contribution)
    assert contribution["support_score"] == SCORE_WITH_ENGAGEMENT
    # A score of at least 55.00 earns a quarter of the 500,000 federal limit.
    assert contribution["max_allowed_cents"] == 125_000
    assert contribution["amount_cents"] == 100_000
    assert contribution["status"] == "PENDING_BOARD"

    scored = read_candidate(candidate["id"])
    assert scored["latest_support_score"] == SCORE_WITH_ENGAGEMENT
    assert scored["pending_support_cents"] == 100_000
    assert scored["committed_support_cents"] == 0
    assert scored["disbursed_support_cents"] == 0


def test_district_engagement_term_is_the_only_difference_between_two_districts():
    """Only the district engagement term separates two otherwise equal candidates.

    PRD 3.9: "The fourth is a cross-entity input, and it is what ties political
    money back to grassroots work".
    PRD 3.9: "The result is written to the contribution's `support_score` and also
    copied to the candidate's `latest_support_score`, which therefore always
    reflects the most recently created contribution for that candidate."

    Design: Difficulty/combinatorial_formula/candidate_support_score_four_input_nonlinear_blend
    """
    setup_live_campaign()
    fund = open_fund()

    mobilised = register_candidate(**CHALLENGER)
    quiet = register_candidate(**{**CHALLENGER, "name": "Blake Rowe", "district_code": "TX-07"})

    mobilised_contribution = propose_contribution(
        fund["id"], mobilised["id"], amount_cents=100_000
    )
    quiet_contribution = propose_contribution(fund["id"], quiet["id"], amount_cents=100_000)

    assert mobilised_contribution["support_score"] == SCORE_WITH_ENGAGEMENT
    assert quiet_contribution["support_score"] == SCORE_WITHOUT_ENGAGEMENT
    assert round(mobilised_contribution["support_score"]
                 - quiet_contribution["support_score"], 2) == 3.00
    # Both sit in the same allowance tier, so the ceiling does not diverge.
    assert mobilised_contribution["max_allowed_cents"] == 125_000
    assert quiet_contribution["max_allowed_cents"] == 125_000
    assert read_candidate(quiet["id"])["latest_support_score"] == SCORE_WITHOUT_ENGAGEMENT


def test_filing_cycle_fee_reads_the_posture_from_before_the_cycle():
    """The restricted surcharge is never charged by the flip the cycle causes.

    PRD 3.8: "Read the posture **as it was before this cycle** and assemble the
    fee from it. The fee is a base of 15,000 cents; plus a surcharge of 5,000
    cents if and only if that pre-cycle posture was `RESTRICTED`; plus a late
    penalty of 25,000 cents if and only if `filed_on_date` falls after the due
    date of the named period".
    PRD 3.8: "The posture recomputed later in this same request is never the
    value used here, so the surcharge is charged at most once per cycle and is
    never re-charged by the flip it may itself cause."

    Design: Difficulty/combinatorial_formula/filing_cycle_surcharge_uses_pre_cycle_posture_pinned_order
    """
    funded = setup_funded_fund(
        min_reserve_cents=150_000, receipt_amount_cents=200_000, received_date="2026-06-01"
    )
    fund_id = funded["fund"]["id"]
    assert funded["fund"]["available_balance_cents"] == 200_000
    assert funded["fund"]["posture"] == "OPEN"

    # First quarter, filed long after its 2026-04-20 deadline: base plus penalty.
    first = run_filing_cycle(fund_id, period_code="2026Q1", filed_on_date="2026-08-01")
    assert first["filing_fee_accrued_cents"] == 40_000
    assert first["available_balance_cents"] == 160_000
    assert first["posture"] == "OPEN"
    assert first["filings_completed_count"] == 1
    assert first["last_filed_period_code"] == "2026Q1"

    # Second quarter, also late. The pre-cycle posture is still OPEN, so the fee
    # is 40,000 rather than 45,000 even though this very cycle restricts the fund.
    second = run_filing_cycle(fund_id, period_code="2026Q2", filed_on_date="2026-08-01")
    assert second["filing_fee_accrued_cents"] == 80_000
    assert second["available_balance_cents"] == 120_000
    assert second["posture"] == "RESTRICTED"
    assert second["filings_completed_count"] == 2
    assert_fund_invariants(second)


def test_third_cycle_adds_the_restricted_surcharge_and_advances_the_calendar():
    """Once the fund is restricted the next cycle pays the surcharge, once.

    PRD 3.8: "Add the fee to `filing_fee_accrued_cents`, increment
    `filings_completed_count` by one, set `last_filed_period_code` to the
    supplied `period_code`, and recompute `available_balance_cents` from the
    accumulators again."
    PRD 3.8: "The system must satisfy a conservation identity before and after
    every fund-touching write: `receipts_total_cents` equals the sum of
    `available_balance_cents`, `committed_balance_cents`, `disbursed_total_cents`
    and `filing_fee_accrued_cents`."

    Design: Difficulty/combinatorial_formula/filing_cycle_surcharge_uses_pre_cycle_posture_pinned_order
    """
    funded = setup_funded_fund(
        min_reserve_cents=150_000, receipt_amount_cents=200_000, received_date="2026-06-01"
    )
    fund_id = funded["fund"]["id"]
    run_filing_cycle(fund_id, period_code="2026Q1", filed_on_date="2026-08-01")
    restricted = run_filing_cycle(fund_id, period_code="2026Q2", filed_on_date="2026-08-01")
    assert restricted["posture"] == "RESTRICTED"

    # 2026Q3 is not yet due on 2026-08-01, so only base plus surcharge apply.
    third = run_filing_cycle(fund_id, period_code="2026Q3", filed_on_date="2026-08-01")
    assert third["filing_fee_accrued_cents"] == 100_000
    assert third["available_balance_cents"] == 100_000
    assert third["posture"] == "RESTRICTED"
    assert third["filings_completed_count"] == 3
    assert third["last_filed_period_code"] == "2026Q3"

    final = read_fund(fund_id)
    assert final["receipts_total_cents"] == 200_000
    assert final["committed_balance_cents"] == 0
    assert final["disbursed_total_cents"] == 0
    assert_fund_invariants(final)


PER_ACTIVITY_HOURS = (1.111, 2.222, 3.333)
PER_ACTIVITY_STAFF_COST = (9_444, 18_887, 28_331)
THREE_ACTIVITIES = [
    {"activity_date": "2026-07-05", "hours": 1.111, "expenditure_cents": 100_000},
    {"activity_date": "2026-07-06", "hours": 2.222, "expenditure_cents": 100_000},
    {"activity_date": "2026-07-07", "hours": 3.333, "expenditure_cents": 100_000},
]


def test_method_b_rounds_each_activity_before_adding_them_up():
    """Rounding once per row, then summing, is the pinned order.

    PRD 3.6: "The rounding order is pinned and is not negotiable: round once per
    activity and only then add up. Summing the hours of every activity first and
    rounding the product once at the end produces a different cent total, and
    that form is wrong here."
    PRD 2.6: "where a rate is applied per row and the results are then summed,
    the rounding happens **once per row, before the sum** — never once at the end
    over a summed quantity."

    Design: Difficulty/combinatorial_formula/method_b_staff_cost_rounded_per_activity_not_after_summing
    """
    state = setup_open_report_with_activities(THREE_ACTIVITIES, basis="METHOD_B")
    report = state["report"]

    assert report["included_activity_count"] == 3
    assert report["method_a_total_cents"] == 300_000
    # 9,444 + 18,887 + 28,331 = 56,662 of staff cost, never the 56,661 that a
    # single rounding of 6.666 hours would produce.
    assert report["method_b_total_cents"] == 356_662
    assert report["method_b_total_cents"] != 356_661
    assert report["filed_total_cents"] == 356_662


def test_each_activity_carries_its_own_rounded_staff_cost():
    """The per-activity staff cost is derived for that activity alone.

    PRD 3.5: "`staff_cost_cents` is the in-house labour value of this one
    activity: its `hours` multiplied by the association's standard staff rate of
    8500 cents per hour — 85 dollars — rounded half up to a whole number of
    cents. This rounding is performed for this activity alone and is never
    re-derived from a summed hour total."
    PRD 3.5: "The activity's `expenditure_cents` is added to the registration's
    `ytd_reportable_cents` and its `hours` are added to the registration's
    `ytd_reportable_hours`, the latter held to three decimals rounded half up; both
    accumulators must always equal the sum over the registration's `LOGGED` activities
    alone."

    Design: Difficulty/combinatorial_formula/method_b_staff_cost_rounded_per_activity_not_after_summing
    """
    state = setup_open_report_with_activities(THREE_ACTIVITIES, basis="METHOD_B")
    registration_id = state["registration"]["id"]

    for activity, hours, staff_cost in zip(
        state["activities"], PER_ACTIVITY_HOURS, PER_ACTIVITY_STAFF_COST
    ):
        assert activity["hours"] == hours
        assert activity["staff_cost_cents"] == staff_cost
        assert read_activity(registration_id, activity["id"])["staff_cost_cents"] == staff_cost

    registration = read_registration(registration_id)
    assert registration["ytd_reportable_cents"] == 300_000
    assert registration["ytd_reportable_hours"] == 6.666
