"""The three financial figures, the point ladders they feed, and the penalty rate."""
from test_helpers import (
    assert_ratio,
    assert_score,
    dimension_by_name,
    override_dimensions,
    read_cycle,
    read_dimension_scores,
    read_score_breakdown,
    setup_scored_cycle,
)


def test_fundraising_efficiency_reduces_each_year_to_its_own_rounded_ratio_before_weighting():
    """Three fiscal years whose own fundraising ratios are 0.1333, 0.2000 and 0.3000
    weight out to 0.1867 — not to the 0.1824 that pooling the six cent amounts gives.

    PRD §3.5: "For each available year, the year's ratio is that filing's `fundraising_expense_cents` divided by its `contributions_cents`, rounded half up to four decimal places at this point — before any weighting — except that a year whose `contributions_cents` is exactly zero takes the worst possible ratio of 1.0000 rather than dividing by zero."

    PRD §3.5: "Each available year then contributes a term equal to its rounded ratio multiplied by its rounded renormalised weight, itself rounded half up to four decimal places; those terms are summed, and the sum is rounded half up to four decimal places one final time."

    Design: Difficulty/combinatorial_formula/fundraising_efficiency_pinned_per_year_rounding_order
    """
    scenario = setup_scored_cycle()
    breakdown = read_score_breakdown(
        scenario["cycle"]["id"], scenario["analyst_headers"]
    )

    assert_ratio(breakdown["fundraising_efficiency"], 0.1867, "fundraising_efficiency")
    assert round(float(breakdown["fundraising_efficiency"]), 4) != 0.1824


def test_financial_health_awards_points_on_three_ladders_from_the_three_pinned_figures():
    """A ratio of 0.7500 earns 15 points, an efficiency of 0.1867 earns 9 and 7.20
    months of reserve earn 5, for 29 of the dimension's 40 points.

    PRD §3.5: "The efficiency ladder rewards smaller values: 12 points when `fundraising_efficiency` is at most 0.10, otherwise 9 at 0.20 or less, otherwise 5 at 0.35 or less, otherwise 0."

    PRD §3.5: "The reserve ladder rewards larger values again: 8 points when `months_of_reserve` is at least 12, otherwise 5 at 6 or more, otherwise 2 at 3 or more, otherwise 0."

    PRD §3.5: "Otherwise it is that filing's `net_assets_cents` multiplied by the twelve months in a year and divided by `total_expense_cents`, rounded half up to two decimal places."

    Design: Difficulty/combinatorial_formula/fundraising_efficiency_pinned_per_year_rounding_order
    """
    scenario = setup_scored_cycle()
    breakdown = read_score_breakdown(
        scenario["cycle"]["id"], scenario["analyst_headers"]
    )

    assert_ratio(breakdown["program_expense_ratio"], 0.7500, "program_expense_ratio")
    assert_score(breakdown["months_of_reserve"], 7.20, "months_of_reserve")

    financial = dimension_by_name(scenario["dimension_scores"], "FINANCIAL_HEALTH")
    assert financial["raw_points"] == 29
    assert financial["max_points"] == 40
    assert_score(financial["normalized_score"], 72.50, "FINANCIAL_HEALTH normalized_score")
    assert_score(
        financial["data_completeness_pct"], 100.00, "FINANCIAL_HEALTH data_completeness_pct"
    )


def test_penalty_rate_is_looked_up_from_the_pre_penalty_weighted_sum():
    """A weighted sum of 84.63 bands B, so the cycle's single failed standard costs
    1.50 points rather than the 1.00 a band-C cycle would pay.

    PRD §3.6: "**Step three** derives a band from that **pre-penalty** weighted sum: band A when the weighted sum is at least 90, band B at 75 or more, band C at 60 or more, band D below that."

    PRD §3.6: "**Step four** computes the penalty, and the band is what sets its rate: 2.0 points per failed standard in band A, 1.5 in band B, 1.0 in band C and 0.5 in band D, multiplied by the cycle's `failed_standard_count` and rounded half up to two decimal places."

    Design: Difficulty/combinatorial_formula/composite_penalty_rate_keyed_on_pre_penalty_band
    """
    scenario = setup_scored_cycle()
    breakdown = read_score_breakdown(
        scenario["cycle"]["id"], scenario["analyst_headers"]
    )

    assert breakdown["failed_standard_count"] == 1
    assert_score(breakdown["weighted_sum_final"], 84.63, "weighted_sum_final")
    assert breakdown["final_band"] == "B"
    assert_score(breakdown["final_penalty"], 1.50, "final_penalty")
    assert_score(breakdown["final_composite_score"], 83.13, "final_composite_score")


def test_override_into_band_c_cuts_the_penalty_with_no_change_in_failed_standard_count():
    """Marking the financial dimension down to 18 of 40 points drops the weighted sum
    to 73.63, and the same single failed standard now costs 1.00 instead of 1.50.

    PRD §3.6: "Banding before the penalty rather than after it, or grading from the weighted sum rather than from the composite, produces different published grades on identical inputs; deriving the penalty rate from the post-penalty score is a fixed-point trap with no defined answer."

    PRD §3.6: "On success each named dimension row takes its supplied `raw_points`, recomputes `normalized_score` and `weighted_contribution`, stores the shared `override_reason` and the acting `X-User-ID` as `overridden_by_user_id`, and advances its own `version` counter by one."

    Design: Difficulty/combinatorial_formula/composite_penalty_rate_keyed_on_pre_penalty_band
    """
    scenario = setup_scored_cycle()
    cycle_id = scenario["cycle"]["id"]
    financial = dimension_by_name(scenario["dimension_scores"], "FINANCIAL_HEALTH")

    override_dimensions(
        cycle_id,
        [{"dimension_score_id": financial["id"], "raw_points": 18}],
        read_cycle(cycle_id)["version"],
        override_reason="restatement pending, financial dimension marked down by review panel",
    )

    rows = read_dimension_scores(cycle_id, scenario["analyst_headers"])
    overridden = dimension_by_name(rows, "FINANCIAL_HEALTH")
    assert overridden["status"] == "OVERRIDDEN"
    assert overridden["raw_points"] == 18
    assert_score(overridden["normalized_score"], 45.00, "FINANCIAL_HEALTH normalized_score")

    breakdown = read_score_breakdown(cycle_id, scenario["analyst_headers"])
    assert breakdown["failed_standard_count"] == 1
    assert_score(breakdown["weighted_sum_final"], 73.63, "weighted_sum_final")
    assert breakdown["final_band"] == "C"
    assert_score(breakdown["final_penalty"], 1.00, "final_penalty")

    cycle = read_cycle(cycle_id)
    assert_score(cycle["final_composite_score"], 72.63, "final_composite_score")
    assert cycle["grade"] == "MEETS_STANDARDS"
