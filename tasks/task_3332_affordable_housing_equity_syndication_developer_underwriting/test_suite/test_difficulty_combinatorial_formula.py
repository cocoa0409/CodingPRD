"""Depth: multi-stage formulas whose rounding points are pinned.

Both instances here assert numbers re-derived from the PRD's own arithmetic:
the capital-call amount (milestone share rounded first, adjuster applied to the
rounded share) and the watch-list risk score (each weighted term rounded before
the terms are summed, then clamped).
"""

import pytest

from test_helpers import (
    api_client,
    get_success_data,
    list_project_capital_calls,
    read_project,
    resolve_review,
    schedule_capital_call,
    set_logical_clock,
    setup_canonical_scenario,
    setup_committed_project,
    issue_call,
    settle_call,
    validate_success,
)

_CLOCK_ISSUE_C1 = "2026-10-05T00:00:00Z"
_CLOCK_ISSUE_C2 = "2026-12-05T00:00:00Z"
_CLOCK_PAST_DEADLINE = "2029-01-15T00:00:00Z"


def _build_two_call_scenario(am_headers):
    """Committed project whose delivery ratio sits in the 0.12 band.

    Riverside Commons is awarded 912345678 credit dollars and 830000000 are
    delivered, so the ratio is 0.9097 and the band is 0.12. C1 (share 0.20) is
    issued and settled in full; C2 (share 0.15) is issued at the same band. A
    later correction drops the delivered total to 500000000, which moves the
    band to 0.20.
    """
    scenario = setup_committed_project()
    project_id = scenario.project["id"]
    allocation_id = scenario.allocation["id"]

    get_success_data(
        api_client.record_allocation_delivery(
            project_id, allocation_id, 830000000, am_headers
        )
    )

    call1 = schedule_capital_call(
        project_id,
        "CONSTRUCTION_START",
        scheduled_date="2026-10-01T00:00:00Z",
        due_date="2026-10-31T00:00:00Z",
        milestone_share=0.20,
    )
    set_logical_clock(_CLOCK_ISSUE_C1)
    call1 = issue_call(call1["id"])
    call1 = settle_call(
        call1["id"], call1["called_amount_cents"], scenario.investor["id"]
    )

    call2 = schedule_capital_call(
        project_id,
        "CONSTRUCTION_50PCT",
        scheduled_date="2026-12-01T00:00:00Z",
        due_date="2026-12-31T00:00:00Z",
        milestone_share=0.15,
    )
    set_logical_clock(_CLOCK_ISSUE_C2)
    call2 = issue_call(call2["id"])

    get_success_data(
        api_client.record_allocation_delivery(
            project_id, allocation_id, 500000000, am_headers
        )
    )
    return scenario, call1, call2


def test_call_amount_rounds_the_milestone_share_before_the_adjuster(
    asset_manager_headers,
):
    """PRD §3.5: "The `base_call_cents` is the project's `underwritten_equity_cents`
    multiplied by the call's `milestone_share`, rounded half-up to a whole cent.
    The `called_amount_cents` is then the `base_call_cents` multiplied by one plus
    the `credit_delivery_adjuster_pct`, rounded half-up again."

    Underwritten equity is 529436038 and the share is 0.15, so the base is
    round(79415405.7) = 79415406; at the 0.12 band the called amount is
    round(79415406 * 1.12) = 88945255, whereas rounding the unrounded share once
    would give 88945254.

    Design: Difficulty/combinatorial_formula/capital_call_adjusted_amount_pinned_two_step_rounding
    """
    _scenario, _call1, call2 = _build_two_call_scenario(asset_manager_headers)

    assert call2["base_call_cents"] == 79415406, (
        "the milestone share is rounded before the adjuster is applied"
    )
    assert call2["credit_delivery_adjuster_pct"] == pytest.approx(0.12, abs=1e-9), (
        "a delivery ratio of 830000000/912345678 = 0.9097 selects the 0.12 band"
    )
    assert call2["called_amount_cents"] == 88945255, (
        "the adjuster is applied to the already-rounded base"
    )


def test_call_adjust_ratchets_the_adjuster_upward_never_down(asset_manager_headers):
    """PRD §3.5: "The adjuster actually pinned on the call is the greater of that
    band value and the adjuster the call already carries, so the adjuster ratchets
    upward and never falls."
    PRD §3.5: "Adjustment recomputes `credit_delivery_adjuster_pct` and
    `called_amount_cents` under the ratchet rule."

    C1 was pinned at 0.12; after the delivery correction the ratio is 0.548 and
    the band is 0.20, so the adjuster rises to 0.20 and the called amount becomes
    round(105887208 * 1.20) = 127064650.

    Design: Difficulty/combinatorial_formula/capital_call_adjusted_amount_pinned_two_step_rounding
    """
    scenario, call1, _call2 = _build_two_call_scenario(asset_manager_headers)

    assert call1["base_call_cents"] == 105887208
    assert call1["credit_delivery_adjuster_pct"] == pytest.approx(0.12, abs=1e-9)
    assert call1["status"] == "PAID"

    adjusted = get_success_data(api_client.adjust_capital_call(call1["id"], asset_manager_headers))

    assert adjusted["credit_delivery_adjuster_pct"] == pytest.approx(0.20, abs=1e-9), (
        "the ratchet raises the pinned adjuster to the newly selected band"
    )
    assert adjusted["called_amount_cents"] == 127064650
    assert adjusted["status"] == "ADJUSTED"


def test_risk_score_rounds_each_weighted_term_before_summing(asset_manager_headers):
    """PRD §3.7: "The occupancy term is 35 multiplied by the `occupancy_pct`.
    The debt-service term is 30 multiplied by the lesser of the `dscr_observed`
    and 1.5, divided by 1.5. The reserve term is 20 when the `reserve_balance_cents`
    is below 50000000, and zero otherwise."
    PRD §3.7: "The raw score is the sum of the four terms, and the `risk_score` is
    that sum clamped into the range from zero to 100."

    Occupancy 0.87 gives 30.45 -> 30, DSCR 1.20 gives 24.0 -> 24 and a 20000000
    reserve gives 20, so the score is 74. Occupancy 0.10 gives 3.5 -> 4 and DSCR
    0.10 gives 2.0 -> 2 with a 40000000 reserve, so the score is 26.

    Design: Difficulty/combinatorial_formula/watch_list_risk_score_term_weights_and_ceiling_clamp
    """
    scenario = setup_canonical_scenario(with_subscription=False, with_project=True)
    project_id = scenario.project["id"]

    review_a = get_success_data(
        api_client.create_review(
            project_id,
            {
                "review_period_index": 0,
                "review_period_end": "2026-07-31T00:00:00Z",
                "occupancy_pct": 0.87,
                "dscr_observed": 1.20,
                "reserve_balance_cents": 20000000,
            },
            asset_manager_headers,
        )
    )
    review_b = get_success_data(
        api_client.create_review(
            project_id,
            {
                "review_period_index": 1,
                "review_period_end": "2026-08-31T00:00:00Z",
                "occupancy_pct": 0.10,
                "dscr_observed": 0.10,
                "reserve_balance_cents": 40000000,
            },
            asset_manager_headers,
        )
    )

    assert review_a["risk_score"] == 74
    assert review_b["risk_score"] == 26, (
        "a 3.5-point occupancy term rounds half-up to 4 before the terms are summed"
    )

    resolved = resolve_review(review_a["id"], headers=asset_manager_headers)
    assert resolved["status"] == "WATCH", (
        "a score of 74 falls in the at-least-70 and below-85 band"
    )


def test_risk_score_is_clamped_at_one_hundred_and_counts_date_violations(
    asset_manager_headers,
):
    """PRD §3.7: "The term-violation points are 15 for each of two conditions that
    holds: the logical clock is after the project's `placed_in_service_deadline`,
    and the review's `review_period_end` is after the logical clock."
    PRD §3.7: "The raw score is the sum of the four terms, and the `risk_score` is
    that sum clamped into the range from zero to 100."

    At a clock of 2029-01-15 the 2028-12-31 deadline has passed, so a review whose
    period end is still in the future scores 35 + 30 + 20 + 15 + 15 = 115 and is
    clamped to 100, while a review whose period end has passed scores
    18 + 20 + 0 + 15 = 53.

    Design: Difficulty/combinatorial_formula/watch_list_risk_score_term_weights_and_ceiling_clamp
    """
    scenario = setup_canonical_scenario(with_subscription=False, with_project=True)
    project_id = scenario.project["id"]

    set_logical_clock(_CLOCK_PAST_DEADLINE)

    clamped = get_success_data(
        api_client.create_review(
            project_id,
            {
                "review_period_index": 0,
                "review_period_end": "2030-06-30T00:00:00Z",
                "occupancy_pct": 1.0,
                "dscr_observed": 1.5,
                "reserve_balance_cents": 40000000,
            },
            asset_manager_headers,
        )
    )
    one_violation = get_success_data(
        api_client.create_review(
            project_id,
            {
                "review_period_index": 1,
                "review_period_end": "2025-01-01T00:00:00Z",
                "occupancy_pct": 0.5,
                "dscr_observed": 1.0,
                "reserve_balance_cents": 60000000,
            },
            asset_manager_headers,
        )
    )

    assert clamped["risk_score"] == 100, (
        "a raw sum of 115 must be clamped into the range from zero to 100"
    )
    assert one_violation["risk_score"] == 53, (
        "18 + 20 + 0 plus the single 15-point deadline violation"
    )
