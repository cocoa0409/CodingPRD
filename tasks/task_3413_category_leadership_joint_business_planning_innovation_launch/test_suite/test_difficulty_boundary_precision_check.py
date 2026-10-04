"""Difficulty queue — boundary precision.

Two thresholds exercised exactly on the line: a raw risk total of exactly 25
meets the `at least 25 is WATCH` rung (PRD §3.9), and a negotiation move at
round == 6 exhausts the round budget — rejected and expiring the plan in the
same failed request (PRD §3.1/§2.10). Each test translates one
difficulty-design instance and cites the PRD rule it pins.
"""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_performance_review,
    assert_plan,
    assert_risk_posture_matches_score,
    setup_proposed_plan,
    setup_review_scenario,
    validate_error,
    validate_success,
)

# Review inputs chosen so the raw weighted total is exactly 25.0.
_BOUNDARY_REVIEW_FIELDS = {
    "actual_sales_cents": 750000,
    "sales_target_cents": 1000000,
    "target_distribution_pct": 90,
    "distribution_achieved_pct": 70,
}


def _boundary_review():
    """OPEN review with bias exactly 6.25 and exactly two DISPUTED deductions:
    raw = 0.4*25 + 0.3*20 + 0.2*25 + 0.1*40 = 25.0."""
    return setup_review_scenario(
        committed_forecast=("2027-03-01T00:00:00Z", 400, 425),
        disputed_deductions=2,
        review_fields=dict(_BOUNDARY_REVIEW_FIELDS),
    )


def test_boundary_review_inputs_land_exactly_on_component_values(api):
    """PRD §3.9: "The `sales_attainment_pct` is the `actual_sales_cents` divided by the `sales_target_cents`, expressed as a percent and rounded half-up to 2 decimal places."
    PRD §3.9: "each contributes the absolute difference between its `committed_cases` and its `baseline_cases`, divided by its `baseline_cases`, expressed as a percent; the bias is the mean of those per-forecast figures, rounded half-up to 2 decimal places, and an empty qualifying set yields a bias of exactly 0."
    PRD §3.9: "The `friction_count` tallies the fund's deductions created within the review window — again inclusive of both ends — whose status is `DISPUTED` or `WRITTEN_OFF`, together with those `SETTLED` while `short_paid`."

    The measured inputs land exactly on 75.0 attainment, 6.25 bias, and a
    friction count of 2.

    Design: Difficulty/boundary_precision_check/risk_posture_boundary_at_25
    """
    review = _boundary_review()["review"]

    assert_performance_review(review)
    assert review["sales_attainment_pct"] == pytest.approx(75.0, abs=0.001)
    assert review["forecast_bias_pct"] == pytest.approx(6.25, abs=0.001), (
        f"|425-400|/400*100 must read exactly 6.25, got {review['forecast_bias_pct']}"
    )
    assert review["friction_count"] == 2


def test_score_of_exactly_25_reads_watch(api):
    """PRD §3.9: "The sales component is 100 minus the `sales_attainment_pct`, clamped into the range 0 to 100."
    PRD §3.9: "The distribution component is the `target_distribution_pct` minus the `distribution_achieved_pct`, clamped the same way, so distribution over-delivery scores zero rather than going negative."
    PRD §3.9: "The forecast component takes the `forecast_bias_pct` capped at 25 and multiplies it by 4, scaling a bias of 0 to 25 onto 0 to 100."
    PRD §3.9: "The friction component takes the `friction_count` capped at 5 and multiplies it by 20, scaling zero to five frictions onto 0 to 100."
    PRD §3.9: "The raw score weighs these at 0.40 for sales, 0.30 for distribution, 0.20 for forecast bias, and 0.10 for friction, and the final `risk_score` is that raw total rounded half-up to a whole number and clamped between 0 and 100."
    PRD §3.9: "The `risk_posture` reads straight off the score: at least 75 is `DELIST_RECOMMENDED`, at least 50 is `AT_RISK`, at least 25 is `WATCH`, and anything below is `HEALTHY`."

    raw = 10 + 6 + 5 + 4 = 25.0 rounds to exactly 25, and the inclusive
    `at least 25` rung flips the posture to WATCH (24 would stay HEALTHY).

    Design: Difficulty/boundary_precision_check/risk_posture_boundary_at_25
    """
    review = _boundary_review()["review"]

    assert_performance_review(review)
    assert review["risk_score"] == 25, (
        f"raw 25.0 must round to exactly 25, got {review['risk_score']}"
    )
    assert review["risk_posture"] == "WATCH", (
        f"25 >= 25 must read WATCH, got {review['risk_posture']}"
    )
    assert_risk_posture_matches_score(review)


def _drive_to_round_six(api, scenario, manufacturer_planner_headers):
    """Five successful alternating moves from a fresh PROPOSED plan (round 1),
    leaving negotiation_round == 6 with the plan COUNTERED."""
    plans = []
    for i, target in enumerate([9, 10, 9, 10, 9]):
        headers = scenario["buyer_headers"] if i % 2 == 0 else manufacturer_planner_headers
        plans.append(
            validate_success(
                api.negotiate_plan(scenario["plan"]["id"], {"growth_target_pct": target}, headers),
                200,
            )
        )
    return plans


def test_five_moves_reach_the_last_legal_round(api, manufacturer_planner_headers):
    """PRD §3.1: "A plan is born directly into `PROPOSED` with its `negotiation_round` at 1."
    PRD §3.1: "The exchange is capped at a round budget of 6: when a negotiation move is attempted while the plan's `negotiation_round` has already reached 6, the request is rejected with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` (HTTP 409), and in the very same failed request the plan auto-transitions to `EXPIRED` with its `version` incremented — the exhaustion error and the expiration are inseparable, whether the plan was sitting `PROPOSED` or `COUNTERED`."

    The move carrying the round from 5 to 6 still succeeds: round 6, COUNTERED,
    is the last legal state of the bounded exchange.

    Design: Difficulty/boundary_precision_check/negotiation_round_exhaustion_at_six
    """
    scenario = setup_proposed_plan()
    plans = _drive_to_round_six(api, scenario, manufacturer_planner_headers)

    last = plans[-1]
    assert_plan(last)
    assert last["negotiation_round"] == 6, (
        f"five successful moves from round 1 must reach round 6, got {last['negotiation_round']}"
    )
    assert last["status"] == "COUNTERED"
    assert last["growth_target_pct"] == 9
    assert last["version"] == scenario["plan"]["version"] + 5


def test_move_at_round_six_fails_and_expires_the_plan(api, manufacturer_planner_headers):
    """PRD §3.1: "The exchange is capped at a round budget of 6: when a negotiation move is attempted while the plan's `negotiation_round` has already reached 6, the request is rejected with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` (HTTP 409), and in the very same failed request the plan auto-transitions to `EXPIRED` with its `version` incremented — the exhaustion error and the expiration are inseparable, whether the plan was sitting `PROPOSED` or `COUNTERED`."
    PRD §2.10: "A negotiation move attempted when the round budget is exhausted is rejected with `ERR_NEGOTIATION_ROUNDS_EXHAUSTED` — and the plan still transitions to `EXPIRED`, version incremented, inside that same failed request."
    PRD §3.1: "on success the plan's `growth_target_pct` is replaced by the proposed value, `negotiation_round` climbs by 1, and the plan's `version` increments as the plan moves `PROPOSED → COUNTERED`."

    The sixth move at round == 6 is rejected, the plan lands EXPIRED with its
    version bumped inside the same failed request, and the round — which
    climbs only on success — stays at 6.

    Design: Difficulty/boundary_precision_check/negotiation_round_exhaustion_at_six
    """
    scenario = setup_proposed_plan()
    plans = _drive_to_round_six(api, scenario, manufacturer_planner_headers)
    pre_failure_version = plans[-1]["version"]

    # Round 6 sits COUNTERED, so the manufacturer is the lawful mover — the
    # rejection below is the round budget, not the mover mapping.
    validate_error(
        api.negotiate_plan(
            scenario["plan"]["id"], {"growth_target_pct": 10}, manufacturer_planner_headers
        ),
        ApiErrorId.ERR_NEGOTIATION_ROUNDS_EXHAUSTED,
    )

    final = validate_success(api.get_plan(scenario["plan"]["id"], manufacturer_planner_headers), 200)
    assert_plan(final)
    assert final["status"] == "EXPIRED", (
        f"the failed move must auto-expire the plan, got {final['status']}"
    )
    assert final["negotiation_round"] == 6, (
        f"the rejected move must not climb the round, got {final['negotiation_round']}"
    )
    assert final["version"] == pre_failure_version + 1, (
        "the EXPIRED transition increments the version inside the failed request (PRD §2.10)"
    )
