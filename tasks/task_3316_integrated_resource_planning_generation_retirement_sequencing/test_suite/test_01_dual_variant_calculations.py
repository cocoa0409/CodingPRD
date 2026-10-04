"""Dual-variant calculations: load forecasting and sensitivity scoring (PRD §3.1, §3.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_forecast,
    add_portfolio,
    add_position,
    compute_snapshot,
    create_plan,
    get_success_data,
    register_candidate,
    register_resource,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import PLANNER


def _setup_dual_variant_plan():
    """Plan with identical BASE and HIGH_ELECTRIFICATION forecasts for 2030,
    a preferred portfolio, and one 500 MW GAS_CC fleet unit."""
    plan = create_plan(plan_name="IRP 2030", cycle_year=2026, planning_horizon_years=15)
    fc = add_forecast(plan["id"], scenario_tag="BASE", forecast_year=2030,
                      residential_mw=1000, commercial_mw=800, industrial_mw=500,
                      electrification_mw=200)
    add_forecast(plan["id"], scenario_tag="HIGH_ELECTRIFICATION", forecast_year=2030,
                 residential_mw=1000, commercial_mw=800, industrial_mw=500,
                 electrification_mw=200)
    portfolio = add_portfolio(plan["id"], portfolio_name="PF-Main", preferred_flag=True)
    register_resource(unit_name="GAS-CC-1", resource_type="GAS_CC", nameplate_mw=500,
                      in_service_year=2020, fuel_type="NATURAL_GAS")
    return plan, fc, portfolio


def test_load_forecasting_coincident_vs_net_peak_margins(api):
    """PRD §3.1: "Under the `NET_PEAK` variant — which recognizes that vehicle and
    building electrification charging shifts off-peak — the electrification contribution
    counts at only sixty percent of its value (a factor of 0.60), while the other three
    classes are treated identically."
    PRD §3.1: "the `NET_PEAK` variant exists only as a snapshot-time request (§3.5),
    where the same inputs produce a lower modeled load and therefore a higher capacity
    margin."

    Design: Difficulty/dual_variant_calc/load_forecasting_coincident_vs_net_peak
    """
    plan, fc, portfolio = _setup_dual_variant_plan()

    coincident = compute_snapshot(portfolio["id"], forecast_year=2030, scenario_tag="BASE")
    # A (portfolio, forecast_year) pair hosts at most one snapshot (PRD §3.5), so the
    # NET_PEAK comparison runs on a sibling portfolio over identical inputs.
    portfolio_np = add_portfolio(plan["id"], portfolio_name="PF-NetPeak",
                                 preferred_flag=False)
    net_peak = compute_snapshot(
        portfolio_np["id"], forecast_year=2030, scenario_tag="HIGH_ELECTRIFICATION",
        variant="NET_PEAK",
    )

    assert coincident["load_mw"] == pytest.approx(2475.00, abs=0.005)
    assert coincident["capacity_margin_mw"] == pytest.approx(-2406.25, abs=0.005)
    assert net_peak["load_mw"] == pytest.approx(2395.00, abs=0.005)
    assert net_peak["capacity_margin_mw"] == pytest.approx(-2314.25, abs=0.005)
    # Same inputs, lower modeled load under NET_PEAK -> strictly higher capacity margin.
    assert net_peak["capacity_margin_mw"] > coincident["capacity_margin_mw"]


def test_load_forecasting_stored_row_is_coincident(api):
    """PRD §3.1: "The stored `effective_load_mw` on a forecast row always reflects the
    `COINCIDENT` variant; the `NET_PEAK` variant exists only as a snapshot-time request
    (§3.5), where the same inputs produce a lower modeled load and therefore a higher
    capacity margin."

    Design: Difficulty/dual_variant_calc/load_forecasting_coincident_vs_net_peak
    """
    plan, fc, portfolio = _setup_dual_variant_plan()

    resp = api.get_forecast(plan["id"], fc["id"], PLANNER)
    stored = validate_success(resp)
    assert stored["total_peak_mw"] == pytest.approx(2500.00, abs=0.005)
    assert stored["effective_load_mw"] == pytest.approx(2475.00, abs=0.005)

    # Even after a NET_PEAK snapshot is computed, the stored row stays COINCIDENT.
    compute_snapshot(portfolio["id"], forecast_year=2030,
                     scenario_tag="HIGH_ELECTRIFICATION", variant="NET_PEAK")
    resp = api.get_forecast(plan["id"], fc["id"], PLANNER)
    stored_after = validate_success(resp)
    assert stored_after["effective_load_mw"] == pytest.approx(2475.00, abs=0.005)


def _setup_sensitivity_plan():
    """Plan with one 253.8 MW GAS_CC position and a 2031 snapshot."""
    plan = create_plan(plan_name="IRP Sens", cycle_year=2026, planning_horizon_years=15)
    add_forecast(plan["id"], scenario_tag="BASE", forecast_year=2031, residential_mw=100)
    portfolio = add_portfolio(plan["id"], portfolio_name="PF-Sens", preferred_flag=True)
    candidate = register_candidate(
        candidate_name="GAS-CC-REP", resource_type="GAS_CC", nameplate_mw=500,
        online_year=2029, capex_usd_per_kw=1200, fixed_om_usd_per_kw_year=15,
        fuel_type="NATURAL_GAS", build_lead_years=3,
    )
    add_position(portfolio["id"], candidate["id"], committed_mw=253.8)
    snapshot = compute_snapshot(portfolio["id"], forecast_year=2031, scenario_tag="BASE")
    return plan, snapshot


def test_sensitivity_fuel_cost_plus_vs_market(api):
    """PRD §3.7: "the default `COST_PLUS` variant moves only the fuel share of cost,
    so the adjusted score is the base score scaled by one plus thirty-five percent of
    the delta — the base multiplied by one plus the product of a 0.35 fuel share and
    `delta_pct`; the `MARKET` variant moves the full score with the price, so the
    adjusted score is the base multiplied by one plus `delta_pct`, yielding a
    materially larger swing from the same inputs."

    Design: Difficulty/dual_variant_calc/sensitivity_fuel_cost_plus_vs_market
    """
    plan, snapshot = _setup_sensitivity_plan()

    resp = api.create_sensitivity(
        plan["id"],
        {"snapshot_id": snapshot["id"], "dimension": "FUEL_PRICE",
         "delta_pct": 0.25, "scoring_variant": "COST_PLUS"},
        PLANNER,
    )
    cost_plus = validate_success(resp, expected_status=201)
    resp = api.create_sensitivity(
        plan["id"],
        {"snapshot_id": snapshot["id"], "dimension": "FUEL_PRICE",
         "delta_pct": 0.25, "scoring_variant": "MARKET"},
        PLANNER,
    )
    market = validate_success(resp, expected_status=201)

    assert cost_plus["base_score_usd"] == 29941451
    assert market["base_score_usd"] == 29941451
    assert cost_plus["adjusted_score_usd"] == 32561328
    assert market["adjusted_score_usd"] == 37426814
    # MARKET moves the full score — a materially larger swing from the same inputs.
    assert market["adjusted_score_usd"] - market["base_score_usd"] > (
        cost_plus["adjusted_score_usd"] - cost_plus["base_score_usd"]
    )


def test_sensitivity_fuel_cost_plus_vs_market_negative_delta(api):
    """PRD §3.7: "a signed `delta_pct` perturbation fraction (a value of 0.25 means a
    twenty-five percent increase) that must lie between negative 0.50 and positive
    0.50 inclusive"
    PRD §3.7: "the default `COST_PLUS` variant moves only the fuel share of cost, so
    the adjusted score is the base score scaled by one plus thirty-five percent of the
    delta — the base multiplied by one plus the product of a 0.35 fuel share and
    `delta_pct`; the `MARKET` variant moves the full score with the price, so the
    adjusted score is the base multiplied by one plus `delta_pct`, yielding a
    materially larger swing from the same inputs."

    Design: Difficulty/dual_variant_calc/sensitivity_fuel_cost_plus_vs_market
    """
    plan, snapshot = _setup_sensitivity_plan()

    resp = api.create_sensitivity(
        plan["id"],
        {"snapshot_id": snapshot["id"], "dimension": "FUEL_PRICE",
         "delta_pct": -0.25, "scoring_variant": "COST_PLUS"},
        PLANNER,
    )
    cost_plus = validate_success(resp, expected_status=201)
    resp = api.create_sensitivity(
        plan["id"],
        {"snapshot_id": snapshot["id"], "dimension": "FUEL_PRICE",
         "delta_pct": -0.25, "scoring_variant": "MARKET"},
        PLANNER,
    )
    market = validate_success(resp, expected_status=201)

    # Signed deltas scale both variants downward; MARKET swings further below base.
    assert cost_plus["base_score_usd"] == 29941451
    assert cost_plus["adjusted_score_usd"] == 27321574
    assert market["adjusted_score_usd"] == 22456088
    assert market["base_score_usd"] - market["adjusted_score_usd"] > (
        cost_plus["base_score_usd"] - cost_plus["adjusted_score_usd"]
    )
