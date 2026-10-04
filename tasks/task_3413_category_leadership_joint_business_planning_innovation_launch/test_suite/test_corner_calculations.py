"""Corner queue — calculation surface: event cost estimates, the fund accrual
waterfall, forecast bias, attainment rounding, and distribution projections.

Each test translates one corner-design `calculations` instance and cites the
PRD sentence that pins the asserted rule.
"""
import pytest

from test_helpers import (
    create_launch_with_phases,
    create_penciled_event,
    create_phase_patch_payload,
    create_published_forecast,
    post_accrual,
    setup_activated_plan,
    setup_review_scenario,
    validate_success,
)


def test_event_cost_estimate_uses_latest_published_forecast(api, manufacturer_planner_headers, finance_analyst_headers):
    """PRD §3.2: "The baseline comes from the forecasts the retailer relationship has produced: among the plan's forecasts whose `pub_status` is `PUBLISHED` and whose week bucket contains the event's start — the bucket running from a `week_start` on or before the `start_date` through six days later — the one with the latest `week_start` wins, and no tie is possible because at most one `PUBLISHED` forecast exists per plan and week."
    PRD §3.2: "The estimate itself is that baseline multiplied by the plan's `avg_unit_net_price_cents`, multiplied by the event's `discount_depth_pct`, divided by 100, with a single round-half-up to a whole cent applied at the very end."
    PRD §3.2: "A successful lock moves the event `PENCILED → LOCKED`, adds the estimate to the fund's `event_reserved_cents` — which correspondingly lowers `event_available_cents` — and increments the event's `version`."

    The event starting 2027-03-10 falls in the week bucket of the 2027-03-08
    forecast (baseline 200), not the 2027-03-01 one: round_half_up(
    200 * 450 * 25 / 100 ) = 22500 cents, reserved into the fund at lock.

    Design: Corner/calculations/event_cost_estimate_uses_latest_published_forecast
    """
    scenario = setup_activated_plan()  # weekly_baseline_cases 100, avg_unit_net_price_cents 450
    plan_id = scenario["plan"]["id"]
    fund_id = scenario["fund"]["id"]
    post_accrual(fund_id, "2027-01", 2_000_000)  # event bucket share: 32000 cents
    create_published_forecast(plan_id, week_start="2027-03-01T00:00:00Z", baseline_cases=100)
    create_published_forecast(plan_id, week_start="2027-03-08T00:00:00Z", baseline_cases=200)
    event = create_penciled_event(
        plan_id,
        start_date="2027-03-10T00:00:00Z",
        end_date="2027-03-17T00:00:00Z",
        discount_depth_pct=25,
    )

    locked = validate_success(api.lock_event(event["id"], manufacturer_planner_headers), 200)
    assert locked["status"] == "LOCKED"
    assert locked["estimated_cost_cents"] == 22500, (
        f"estimate must use the latest covering forecast (baseline 200): "
        f"expected 22500, got {locked['estimated_cost_cents']}"
    )

    fund = validate_success(api.get_fund(fund_id, finance_analyst_headers), 200)
    assert fund["event_reserved_cents"] == 22500, (
        f"the lock must reserve the estimate into event_reserved_cents, got {fund['event_reserved_cents']}"
    )


def test_event_cost_estimate_falls_back_to_plan_baseline(api, manufacturer_planner_headers):
    """PRD §3.2: "When no forecast qualifies, the plan's own `weekly_baseline_cases` serves as the fallback baseline."
    PRD §3.2: "The estimate itself is that baseline multiplied by the plan's `avg_unit_net_price_cents`, multiplied by the event's `discount_depth_pct`, divided by 100, with a single round-half-up to a whole cent applied at the very end."

    With no forecasts at all, the lock estimate falls back to the plan
    baseline: round_half_up( 150 * 450 * 25 / 100 ) = 16875 cents.

    Design: Corner/calculations/event_cost_estimate_falls_back_to_plan_baseline
    """
    scenario = setup_activated_plan(weekly_baseline_cases=150)  # avg_unit_net_price_cents 450
    plan_id = scenario["plan"]["id"]
    fund_id = scenario["fund"]["id"]
    post_accrual(fund_id, "2027-01", 1_500_000)  # event bucket share: 24000 cents
    event = create_penciled_event(
        plan_id,
        start_date="2027-03-10T00:00:00Z",
        end_date="2027-03-17T00:00:00Z",
        discount_depth_pct=25,
    )

    locked = validate_success(api.lock_event(event["id"], manufacturer_planner_headers), 200)
    assert locked["status"] == "LOCKED"
    assert locked["estimated_cost_cents"] == 16875, (
        f"the fallback estimate must read the plan baseline (150): "
        f"expected 16875, got {locked['estimated_cost_cents']}"
    )


def test_fund_split_remainder_routes_to_event_bucket(api, finance_analyst_headers):
    """PRD §3.6: "The period credit is the `invoiced_sales_cents` multiplied by the fund's `accrual_rate_pct` and divided by 100, rounded half-up to a whole cent. The EDLP bucket's share of that credit is the period credit multiplied by the fund's `edlp_split_pct` and divided by 100, again rounded half-up to a whole cent, and the EVENT bucket receives the remainder — the period credit minus the EDLP share — so the rounding remainder always routes to the event side."
    PRD §3.6: "In the same pass the server computes the cash-basis shadow: each bucket's share is multiplied by the collection factor 0.92 and rounded half-up to a whole cent, which makes the cash figures strictly smaller than their accrual counterparts whenever a share is positive."

    A 25025-cent period at 4% accrues a 1001-cent credit; the EDLP share is
    round_half_up(1001 * 0.60) = 601 and the EVENT bucket takes the remainder
    400 — the remainder absorbs the rounding, never the other way. Cash
    shadow: round_half_up(601 * 0.92) = 553 and round_half_up(400 * 0.92) =
    368.

    Design: Corner/calculations/fund_split_remainder_routes_to_event_bucket
    """
    scenario = setup_activated_plan()  # accrual_rate_pct 4, edlp_split_pct 60
    fund_id = scenario["fund"]["id"]
    post_accrual(fund_id, "2027-01", 25_025)

    fund = validate_success(api.get_fund(fund_id, finance_analyst_headers), 200)
    assert fund["edlp_accrued_cents"] == 601, (
        f"EDLP share must be round_half_up(1001 * 0.60) = 601, got {fund['edlp_accrued_cents']}"
    )
    assert fund["event_accrued_cents"] == 400, (
        f"EVENT share must be the remainder 1001 - 601 = 400, got {fund['event_accrued_cents']}"
    )
    assert fund["edlp_cash_cents"] == 553, (
        f"EDLP cash must be round_half_up(601 * 0.92) = 553, got {fund['edlp_cash_cents']}"
    )
    assert fund["event_cash_cents"] == 368, (
        f"EVENT cash must be round_half_up(400 * 0.92) = 368, got {fund['event_cash_cents']}"
    )


def test_forecast_bias_excludes_uncommitted(api):
    """PRD §3.9: "The `forecast_bias_pct` measures how badly committed forecasts missed: among the plan's forecasts that are both `PUBLISHED` and `COMMITTED` with a `week_start` falling inside the review window inclusive of both ends — superseded forecasts never contribute, even committed ones — each contributes the absolute difference between its `committed_cases` and its `baseline_cases`, divided by its `baseline_cases`, expressed as a percent; the bias is the mean of those per-forecast figures, rounded half-up to 2 decimal places, and an empty qualifying set yields a bias of exactly 0."
    PRD §3.9: "The raw score weighs these at 0.40 for sales, 0.30 for distribution, 0.20 for forecast bias, and 0.10 for friction, and the final `risk_score` is that raw total rounded half-up to a whole number and clamped between 0 and 100."
    PRD §3.9: "The `risk_posture` reads straight off the score: at least 75 is `DELIST_RECOMMENDED`, at least 50 is `AT_RISK`, at least 25 is `WATCH`, and anything below is `HEALTHY`."

    Only the COMMITTED forecast (baseline 1000, committed 1100 -> 10.0%)
    feeds the mean; the UNCOMMITTED 5000-case forecast in the same window is
    excluded, so bias is 10.0 and risk_score is 0.4*10 + 0.3*0 + 0.2*40 +
    0.1*0 = 12, posture HEALTHY.

    Design: Corner/calculations/forecast_bias_excludes_uncommitted
    """
    scenario = setup_review_scenario(
        committed_forecast=("2027-03-01T00:00:00Z", 1000, 1100),
        published_forecasts=(("2027-03-08T00:00:00Z", 5000),),
        review_fields={
            "actual_sales_cents": 900000,
            "sales_target_cents": 1000000,
            "target_distribution_pct": 90,
            "distribution_achieved_pct": 90,
        },
    )
    review = scenario["review"]
    assert review["forecast_bias_pct"] == pytest.approx(10.0, abs=0.001), (
        f"only the COMMITTED forecast may feed the bias mean, got {review['forecast_bias_pct']}"
    )
    assert review["risk_score"] == 12, (
        f"risk_score must be round_half_up(0.4*10 + 0.3*0 + 0.2*40 + 0.1*0) = 12, got {review['risk_score']}"
    )
    assert review["risk_posture"] == "HEALTHY", (
        f"a score of 12 sits below the WATCH floor, got {review['risk_posture']}"
    )


def test_forecast_bias_empty_set_zero(api):
    """PRD §3.9: "The `forecast_bias_pct` measures how badly committed forecasts missed: among the plan's forecasts that are both `PUBLISHED` and `COMMITTED` with a `week_start` falling inside the review window inclusive of both ends — superseded forecasts never contribute, even committed ones — each contributes the absolute difference between its `committed_cases` and its `baseline_cases`, divided by its `baseline_cases`, expressed as a percent; the bias is the mean of those per-forecast figures, rounded half-up to 2 decimal places, and an empty qualifying set yields a bias of exactly 0."
    PRD §3.9: "The `risk_posture` reads straight off the score: at least 75 is `DELIST_RECOMMENDED`, at least 50 is `AT_RISK`, at least 25 is `WATCH`, and anything below is `HEALTHY`."

    No forecasts at all: the empty qualifying set is not an error — bias is
    exactly 0, and with attainment 100 and distribution met the risk_score is
    0, posture HEALTHY.

    Design: Corner/calculations/forecast_bias_empty_set_zero
    """
    scenario = setup_review_scenario(
        review_fields={
            "actual_sales_cents": 1000000,
            "sales_target_cents": 1000000,
            "target_distribution_pct": 90,
            "distribution_achieved_pct": 90,
        },
    )
    review = scenario["review"]
    assert review["forecast_bias_pct"] == pytest.approx(0.0, abs=0.001), (
        f"an empty qualifying set must yield bias exactly 0, got {review['forecast_bias_pct']}"
    )
    assert review["risk_score"] == 0, f"all four components are zero, got {review['risk_score']}"
    assert review["risk_posture"] == "HEALTHY", (
        f"a zero score reads HEALTHY, got {review['risk_posture']}"
    )


def test_sales_attainment_two_decimal_rounding(api):
    """PRD §3.9: "The `sales_attainment_pct` is the `actual_sales_cents` divided by the `sales_target_cents`, expressed as a percent and rounded half-up to 2 decimal places."
    PRD §3.9: "The sales component is 100 minus the `sales_attainment_pct`, clamped into the range 0 to 100."
    PRD §3.9: "The raw score weighs these at 0.40 for sales, 0.30 for distribution, 0.20 for forecast bias, and 0.10 for friction, and the final `risk_score` is that raw total rounded half-up to a whole number and clamped between 0 and 100."
    PRD §3.9: "The `risk_posture` reads straight off the score: at least 75 is `DELIST_RECOMMENDED`, at least 50 is `AT_RISK`, at least 25 is `WATCH`, and anything below is `HEALTHY`."

    333333 / 1000000 attains 33.33 after the single 2-decimal round-half-up;
    the sales component 100 - 33.33 = 66.67 weighs 0.4 * 66.67 = 26.668 into
    a risk_score of 27 (one final round-half-up), posture WATCH.

    Design: Corner/calculations/sales_attainment_two_decimal_rounding
    """
    scenario = setup_review_scenario(
        review_fields={
            "actual_sales_cents": 333333,
            "sales_target_cents": 1000000,
            "target_distribution_pct": 90,
            "distribution_achieved_pct": 90,
        },
    )
    review = scenario["review"]
    assert review["sales_attainment_pct"] == pytest.approx(33.33, abs=0.001), (
        f"attainment must round half-up to 2 decimals: expected 33.33, got {review['sales_attainment_pct']}"
    )
    assert review["risk_score"] == 27, (
        f"risk_score must be round_half_up(0.4 * 66.67) = 27, got {review['risk_score']}"
    )
    assert review["risk_posture"] == "WATCH", (
        f"a score of 27 clears the WATCH floor of 25, got {review['risk_posture']}"
    )


def test_phase_revise_recomputes_projections(api, manufacturer_planner_headers):
    """PRD §3.5: "The committed read, `projected_distribution_committed_pct`, sums each phase's `distribution_target_pct` with `GATE_PASSED` phases weighted at 1.0 and phases in any other status weighted at 0.0. The pipeline read, `projected_distribution_weighted_pct`, sums the same targets fractionally: a weight of 1.0 for `GATE_PASSED`, 0.25 for `PENDING`, and 0.0 for `GATE_FAILED`."
    PRD §3.5: "Both are stored rounded half-up to 2 decimal places and are refreshed on every phase creation, patch, and evaluation."
    PRD §3.5: "A successful patch applies the field updates, returns a `GATE_FAILED` phase to `PENDING` (a `PENDING` phase simply stays `PENDING`), recomputes the launch's `budget_remaining_cents` as the total budget minus the sum of phase spends, refreshes both distribution projections, and increments the phase's `version`."

    With p1 PASSED (40), p2 PASSED (30), p3 PENDING (20) and p4 GATE_FAILED
    (5), the reads are committed 70 and weighted 75.0. Revising p4 to 10
    returns it to PENDING and recomputes on the patch itself: committed stays
    70 while weighted moves to 40 + 30 + 20*0.25 + 10*0.25 = 77.5.

    Design: Corner/calculations/phase_revise_recomputes_projections
    """
    scenario = setup_activated_plan()
    launch, phases = create_launch_with_phases(
        scenario["plan"]["id"], launch_date="2027-03-01T00:00:00Z"
    )
    ph1, ph2, ph3, ph4 = phases
    for phase, target in ((ph1, 40), (ph2, 30), (ph3, 20), (ph4, 5)):
        validate_success(
            api.patch_launch_phase(
                launch["id"],
                phase["id"],
                create_phase_patch_payload(distribution_target_pct=target, capacity_cases=100),
                manufacturer_planner_headers,
            ),
            200,
        )
    for phase in (ph1, ph2):
        passed = validate_success(
            api.evaluate_launch_phase(launch["id"], phase["id"], manufacturer_planner_headers), 200
        )
        assert passed["status"] == "GATE_PASSED", (
            f"Setup failed: phase {phase['phase_index']} must pass, got {passed['status']}"
        )
    failed = validate_success(
        api.evaluate_launch_phase(launch["id"], ph4["id"], manufacturer_planner_headers), 200
    )
    assert failed["status"] == "GATE_FAILED", (
        f"phase 4 with phase 3 unpassed must fail its gate (weight 0.0), got {failed['status']}"
    )

    before = validate_success(api.get_launch(launch["id"], manufacturer_planner_headers), 200)
    assert before["projected_distribution_committed_pct"] == pytest.approx(70.0, abs=0.001), (
        f"committed read must sum GATE_PASSED targets only, got {before['projected_distribution_committed_pct']}"
    )
    assert before["projected_distribution_weighted_pct"] == pytest.approx(75.0, abs=0.001), (
        f"weighted read must be 40 + 30 + 20*0.25 + 5*0.0 = 75.0, got {before['projected_distribution_weighted_pct']}"
    )

    revised = validate_success(
        api.patch_launch_phase(
            launch["id"], ph4["id"], {"distribution_target_pct": 10}, manufacturer_planner_headers
        ),
        200,
    )
    assert revised["status"] == "PENDING", (
        f"patching a GATE_FAILED phase must return it to PENDING, got {revised['status']}"
    )

    after = validate_success(api.get_launch(launch["id"], manufacturer_planner_headers), 200)
    assert after["projected_distribution_committed_pct"] == pytest.approx(70.0, abs=0.001), (
        f"the revise changes no GATE_PASSED phase, committed must stay 70, got {after['projected_distribution_committed_pct']}"
    )
    assert after["projected_distribution_weighted_pct"] == pytest.approx(77.5, abs=0.001), (
        f"the revise itself recomputes: 40 + 30 + 20*0.25 + 10*0.25 = 77.5, got {after['projected_distribution_weighted_pct']}"
    )
