"""Combinatorial formulas: accreditation aggregate and retirement analysis (PRD §3.5, §3.6)."""
import pytest

from test_helpers import (
    add_forecast,
    add_portfolio,
    compute_snapshot,
    create_plan,
    get_portfolio_version,
    register_candidate,
    register_resource,
    retire_resource,
    validate_success,
)
from test_helpers.fixtures import PLANNER


def _setup_accreditation_plan():
    """DRAFT plan with 2030/2040 BASE forecasts, a preferred portfolio, and a
    300 MW COAL unit in service since 1985."""
    plan = create_plan(plan_name="IRP Accr", cycle_year=2026, planning_horizon_years=20)
    add_forecast(plan["id"], scenario_tag="BASE", forecast_year=2030, residential_mw=10)
    add_forecast(plan["id"], scenario_tag="BASE", forecast_year=2040, residential_mw=10)
    portfolio = add_portfolio(plan["id"], portfolio_name="PF-Accr", preferred_flag=True)
    resource = register_resource(unit_name="COAL-OLD", resource_type="COAL",
                                 nameplate_mw=300, in_service_year=1985, fuel_type="COAL")
    return plan, portfolio, resource


def test_accreditation_age_derate_ramp_at_45(api):
    """PRD §3.5: "The static factors are 0.90 for `COAL`, 0.88 for `GAS_CC`, 0.85 for
    `GAS_CT`, 0.95 for `NUCLEAR`, 0.80 for `HYDRO`, 0.40 for `SOLAR`, 0.15 for `WIND`,
    0.75 for `STORAGE`, and 0.70 for `DEMAND_RESPONSE`."
    PRD §3.5: "between the two, the factor declines linearly by one hundredth per year,
    so age forty-one yields 0.99 and age forty-nine yields 0.91."

    Design: Difficulty/combinatorial_formula/capacity_accreditation_mode_a_multi_input
    """
    plan, portfolio, resource = _setup_accreditation_plan()

    snapshot = compute_snapshot(portfolio["id"], forecast_year=2030, scenario_tag="BASE")
    # Age 45 at 2030: mid-ramp derate 0.95 -> 300 * 0.90 * 0.95 = 256.50.
    assert snapshot["accredited_supply_mw"] == pytest.approx(256.50, abs=0.005)


def test_accreditation_decided_unit_contributes_zero_past_retirement(api):
    """PRD §3.5: "A fleet unit contributes its `nameplate_mw` when it is `ACTIVE`, or
    when it is `DECIDED` and the snapshot's `forecast_year` is strictly earlier than its
    `retirement_year`; otherwise it contributes zero."

    Design: Difficulty/combinatorial_formula/capacity_accreditation_mode_a_multi_input
    """
    plan, portfolio, resource = _setup_accreditation_plan()

    retire_resource(resource["id"], retirement_year=2031, plan_id=plan["id"])
    snapshot = compute_snapshot(portfolio["id"], forecast_year=2040, scenario_tag="BASE")
    # DECIDED with retirement_year 2031: forecast_year 2040 >= 2031 -> zero.
    assert snapshot["accredited_supply_mw"] == pytest.approx(0.00, abs=0.005)


def _setup_retirement_analysis():
    """Plan + decided 300 MW COAL unit (retire 2031) + replacement candidate + snapshot."""
    plan = create_plan(plan_name="IRP RA", cycle_year=2026, planning_horizon_years=20)
    add_forecast(plan["id"], scenario_tag="BASE", forecast_year=2031, residential_mw=10)
    portfolio = add_portfolio(plan["id"], portfolio_name="PF-RA", preferred_flag=True)
    resource = register_resource(unit_name="COAL-RA", resource_type="COAL",
                                 nameplate_mw=300, in_service_year=1985, fuel_type="COAL")
    register_candidate(candidate_name="GAS-CC-REP2", resource_type="GAS_CC",
                       nameplate_mw=500, online_year=2029, capex_usd_per_kw=1200,
                       fixed_om_usd_per_kw_year=15, fuel_type="NATURAL_GAS",
                       build_lead_years=3)
    retire_resource(resource["id"], retirement_year=2031, plan_id=plan["id"])
    snapshot = compute_snapshot(portfolio["id"], forecast_year=2031, scenario_tag="BASE")
    return plan, resource, snapshot


def test_retirement_analysis_compliance_and_fixed_om_components(api):
    """PRD §3.6: "Coal's schedule starts at a base of $42,000 per MW-year, flat for
    years before 2030, and from 2030 onward steps up by $8,000 per MW-year for each year
    past 2030, never dropping below the base."
    PRD §3.6: "The `fixed_om_avoided_usd` is the fixed operating cost avoided: for each
    window year, the unit type's fixed O&M rate per MW-year multiplied by
    `nameplate_mw` — $38,000 for coal, $14,000 for combustion-turbine gas, and $9,000
    for every other type — summed across the window."

    Design: Difficulty/combinatorial_formula/retirement_analysis_mode_b_round_per_component
    """
    plan, resource, snapshot = _setup_retirement_analysis()

    resp = api.create_retirement_analysis(
        resource["id"], {"plan_id": plan["id"], "snapshot_id": snapshot["id"]}, PLANNER
    )
    analysis = validate_success(resp, expected_status=201)

    # Window 2031..2040: 42000 + 48000 + ... + 114000 $/MW-yr x 300 MW = 258,000,000.
    assert analysis["compliance_cost_usd"] == 258000000
    # 38,000 $/MW-yr x 300 MW x 10 years.
    assert analysis["fixed_om_avoided_usd"] == 114000000


def test_retirement_analysis_net_benefit_identity_and_recommendation(api):
    """PRD §3.6: "The bottom line is `net_retirement_benefit_usd`: the compliance cost
    avoided, plus the fixed O&M avoided, minus the replacement cost."
    PRD §3.6: "When the benefit is strictly positive the analysis `recommendation` is
    `RETIRE`; when it is zero or negative the recommendation is `KEEP` — an exactly-zero
    benefit recommends keeping the unit."

    Design: Difficulty/combinatorial_formula/retirement_analysis_mode_b_round_per_component
    """
    plan, resource, snapshot = _setup_retirement_analysis()

    resp = api.create_retirement_analysis(
        resource["id"], {"plan_id": plan["id"], "snapshot_id": snapshot["id"]}, PLANNER
    )
    analysis = validate_success(resp, expected_status=201)

    net = analysis["net_retirement_benefit_usd"]
    assert net == (
        analysis["compliance_cost_usd"]
        + analysis["fixed_om_avoided_usd"]
        - analysis["replacement_cost_usd"]
    )
    # Compliance + fixed O&M dwarf replacement here, so the benefit is positive.
    assert net > 0
    assert analysis["recommendation"] == "RETIRE"
