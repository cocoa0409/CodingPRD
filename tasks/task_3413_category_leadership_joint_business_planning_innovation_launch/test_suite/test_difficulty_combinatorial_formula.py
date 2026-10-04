"""Difficulty queue — combinatorial formulas.

Mode (a): the delisting risk score combines four weighted, clamped, and capped
inputs into one integer with a tiered posture ladder (PRD §3.9). Mode (b): the
fund accrual pins the ORDER of rounding — each period's credit and bucket
shares are rounded to whole cents before any summing (PRD §3.6). Each test
translates one difficulty-design instance and cites the PRD rule it pins.
"""
import pytest

from test_helpers import (
    assert_fund_invariants,
    assert_performance_review,
    assert_risk_posture_matches_score,
    assert_trade_fund,
    setup_activated_plan,
    setup_review_scenario,
    validate_success,
)

# Review inputs chosen so the raw weighted total is exactly 52 (instance a).
_AT_RISK_REVIEW_FIELDS = {
    "actual_sales_cents": 600000,
    "sales_target_cents": 1000000,
    "target_distribution_pct": 90,
    "distribution_achieved_pct": 70,
}


def _at_risk_review_scenario():
    """OPEN review on a launched launch: one committed forecast with bias 30.0
    and seven DISPUTED deductions inside the review window."""
    return setup_review_scenario(
        committed_forecast=("2027-03-01T00:00:00Z", 1000, 1300),
        disputed_deductions=7,
        review_fields=dict(_AT_RISK_REVIEW_FIELDS),
    )


def test_review_inputs_attainment_bias_friction(api):
    """PRD §3.9: "The `sales_attainment_pct` is the `actual_sales_cents` divided by the `sales_target_cents`, expressed as a percent and rounded half-up to 2 decimal places."
    PRD §3.9: "among the plan's forecasts that are both `PUBLISHED` and `COMMITTED` with a `week_start` falling inside the review window inclusive of both ends — superseded forecasts never contribute, even committed ones — each contributes the absolute difference between its `committed_cases` and its `baseline_cases`, divided by its `baseline_cases`, expressed as a percent; the bias is the mean of those per-forecast figures, rounded half-up to 2 decimal places, and an empty qualifying set yields a bias of exactly 0."
    PRD §3.9: "The `friction_count` tallies the fund's deductions created within the review window — again inclusive of both ends — whose status is `DISPUTED` or `WRITTEN_OFF`, together with those `SETTLED` while `short_paid`."

    The three measured inputs: attainment 60.0, bias 30.0, friction 7.

    Design: Difficulty/combinatorial_formula/risk_score_multi_input_threshold
    """
    scenario = _at_risk_review_scenario()
    review = scenario["review"]

    assert_performance_review(review)
    assert review["sales_attainment_pct"] == pytest.approx(60.0, abs=0.001), (
        f"600000/1000000*100 must read 60.0, got {review['sales_attainment_pct']}"
    )
    assert review["forecast_bias_pct"] == pytest.approx(30.0, abs=0.001), (
        f"|1300-1000|/1000*100 must read 30.0, got {review['forecast_bias_pct']}"
    )
    assert review["friction_count"] == 7, (
        f"all seven DISPUTED deductions in the window must count, got {review['friction_count']}"
    )


def test_risk_score_weighted_total_lands_at_risk(api):
    """PRD §3.9: "The sales component is 100 minus the `sales_attainment_pct`, clamped into the range 0 to 100."
    PRD §3.9: "The forecast component takes the `forecast_bias_pct` capped at 25 and multiplies it by 4, scaling a bias of 0 to 25 onto 0 to 100."
    PRD §3.9: "The friction component takes the `friction_count` capped at 5 and multiplies it by 20, scaling zero to five frictions onto 0 to 100."
    PRD §3.9: "The raw score weighs these at 0.40 for sales, 0.30 for distribution, 0.20 for forecast bias, and 0.10 for friction, and the final `risk_score` is that raw total rounded half-up to a whole number and clamped between 0 and 100."
    PRD §3.9: "The `risk_posture` reads straight off the score: at least 75 is `DELIST_RECOMMENDED`, at least 50 is `AT_RISK`, at least 25 is `WATCH`, and anything below is `HEALTHY`."

    raw = 0.4*40 + 0.3*20 + 0.2*min(30,25)*4 + 0.1*min(7,5)*20 = 52, which lands
    in the >= 50 AT_RISK tier while staying below the >= 75 tier.

    Design: Difficulty/combinatorial_formula/risk_score_multi_input_threshold
    """
    scenario = _at_risk_review_scenario()
    review = scenario["review"]

    assert_performance_review(review)
    assert review["risk_score"] == 52, (
        f"weighted raw 16+6+20+10 must round to 52, got {review['risk_score']}"
    )
    assert review["risk_posture"] == "AT_RISK", (
        f"52 >= 50 but < 75 must read AT_RISK, got {review['risk_posture']}"
    )
    assert_risk_posture_matches_score(review)


def _fund_with_two_periods(api, finance_analyst_headers):
    """Zeroed fund (rate 4%, split 60) + two posted periods whose per-period
    rounding diverges from the forbidden sum-then-round order by one cent."""
    scenario = setup_activated_plan(accrual_rate_pct=4, edlp_split_pct=60)
    fund_id = scenario["fund"]["id"]
    validate_success(
        api.post_fund_accrual(
            fund_id, {"period": "2027-01", "invoiced_sales_cents": 1005033}, finance_analyst_headers
        ),
        201,
    )
    fund = validate_success(
        api.post_fund_accrual(
            fund_id, {"period": "2027-02", "invoiced_sales_cents": 777777}, finance_analyst_headers
        ),
        201,
    )
    return fund


def test_fund_credit_rounds_each_period_before_summing(api, finance_analyst_headers):
    """PRD §3.6: "The rounding order is pinned and not negotiable: each period's credit and bucket shares are rounded to whole cents before they are summed into the fund's running totals — summing unrounded period values and rounding once at the end is forbidden, because it produces different cents."

    Per period: round_half_up(40201*0.6)=24121 plus round_half_up(31111*0.6)=
    18667 accumulate to 42788 — the sum-then-round order would yield 42787 and
    is the forbidden variant.

    Design: Difficulty/combinatorial_formula/fund_credit_rounding_per_period_then_sum
    """
    fund = _fund_with_two_periods(api, finance_analyst_headers)

    assert_trade_fund(fund)
    assert fund["edlp_accrued_cents"] == 42788, (
        "per-period rounding must accumulate 24121+18667=42788 (sum-then-round "
        f"would give 42787), got {fund['edlp_accrued_cents']}"
    )
    assert_fund_invariants(fund)


def test_event_remainder_and_invoiced_total_accumulate(api, finance_analyst_headers):
    """PRD §3.6: "the EVENT bucket receives the remainder — the period credit minus the EDLP share — so the rounding remainder always routes to the event side."
    PRD §3.6: "The period's accrual-basis shares accumulate into `edlp_accrued_cents` and `event_accrued_cents`, the cash shares into `edlp_cash_cents` and `event_cash_cents`, the raw invoiced amount into `total_invoiced_cents`, and the fund's `version` increments."

    Event remainders 16080 + 12444 accumulate to 28524; the raw invoiced sales
    accumulate to 1782810.

    Design: Difficulty/combinatorial_formula/fund_credit_rounding_per_period_then_sum
    """
    fund = _fund_with_two_periods(api, finance_analyst_headers)

    assert_trade_fund(fund)
    assert fund["event_accrued_cents"] == 28524, (
        f"event remainders must accumulate 16080+12444=28524, got {fund['event_accrued_cents']}"
    )
    assert fund["total_invoiced_cents"] == 1782810, (
        f"raw invoiced sales must accumulate 1005033+777777=1782810, got {fund['total_invoiced_cents']}"
    )
    assert_fund_invariants(fund)
