"""Calculation corners: derating boundaries, accreditation variant, sensitivity dimensions, waterfall (PRD §3.5–§3.7, §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_forecast,
    add_portfolio,
    add_position,
    compute_snapshot,
    create_plan,
    get_success_data,
    issue_commitment,
    register_candidate,
    register_resource,
    retire_resource,
    setup_approved_plan,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import PLANNER


def test_coal_derate_ramp_and_floor(api):
    """PRD §3.5: "Coal units derate with age, where age is the forecast year minus the
    unit's in-service year: at age forty or below the factor is 1.00; at age fifty or
    above the factor reaches its floor of 0.90; between the two, the factor declines
    linearly by one hundredth per year, so age forty-one yields 0.99 and age forty-nine
    yields 0.91."

    Design: Corner/calculations/coal_derate_ramp_and_floor
    """
    plan = create_plan(plan_name="IRP Der", cycle_year=2026, planning_horizon_years=20)
    for year in (2025, 2030, 2035):
        add_forecast(plan["id"], scenario_tag="BASE", forecast_year=year,
                     residential_mw=10)
    portfolio = add_portfolio(plan["id"], portfolio_name="PF-Der", preferred_flag=True)
    register_resource(unit_name="COAL-DER", resource_type="COAL", nameplate_mw=300,
                      in_service_year=1985, fuel_type="COAL")

    snap_2025 = compute_snapshot(portfolio["id"], forecast_year=2025, scenario_tag="BASE")
    snap_2030 = compute_snapshot(portfolio["id"], forecast_year=2030, scenario_tag="BASE")
    snap_2035 = compute_snapshot(portfolio["id"], forecast_year=2035, scenario_tag="BASE")

    # Age 40: no derate. Age 45: mid-ramp 0.95. Age 50: floor 0.90.
    assert snap_2025["accredited_supply_mw"] == pytest.approx(270.00, abs=0.005)
    assert snap_2030["accredited_supply_mw"] == pytest.approx(256.50, abs=0.005)
    assert snap_2035["accredited_supply_mw"] == pytest.approx(243.00, abs=0.005)


def test_storage_cycle_and_dr_step_derates(api):
    """PRD §3.5: "Storage candidates and units derate with cycles, where cycles are the
    forecast year minus the online year: at twenty cycles or more the factor drops to
    0.75, otherwise 1.00."
    PRD §3.5: "Demand response steps up over time: for forecast years before 2030 the
    factor is 0.85, and from 2030 onward it is 1.00."

    Design: Corner/calculations/storage_cycle_and_dr_step_derates
    """
    # PRD §3.2 requires candidate online_year >= 2026, so the storage 20-cycle cliff
    # is exercised at forecast years 2045/2046 with online_year 2026 (19 vs 20 cycles),
    # and the DR step at 2029/2030 (before vs from 2030).
    plan = create_plan(plan_name="IRP Step", cycle_year=2026, planning_horizon_years=25)
    for year in (2029, 2030, 2045, 2046):
        add_forecast(plan["id"], scenario_tag="BASE", forecast_year=year,
                     residential_mw=10)
    portfolio = add_portfolio(plan["id"], portfolio_name="PF-Step", preferred_flag=True)
    storage = register_candidate(candidate_name="K-STOR", resource_type="STORAGE",
                                 nameplate_mw=200, online_year=2026, capex_usd_per_kw=800,
                                 fixed_om_usd_per_kw_year=12, fuel_type="NONE",
                                 build_lead_years=1)
    dr = register_candidate(candidate_name="K-DR", resource_type="DEMAND_RESPONSE",
                            nameplate_mw=200, online_year=2026, capex_usd_per_kw=100,
                            fixed_om_usd_per_kw_year=5, fuel_type="NONE",
                            build_lead_years=1)
    add_position(portfolio["id"], storage["id"], committed_mw=100)
    add_position(portfolio["id"], dr["id"], committed_mw=100)

    snap_2029 = compute_snapshot(portfolio["id"], forecast_year=2029, scenario_tag="BASE")
    snap_2030 = compute_snapshot(portfolio["id"], forecast_year=2030, scenario_tag="BASE")
    snap_2045 = compute_snapshot(portfolio["id"], forecast_year=2045, scenario_tag="BASE")
    snap_2046 = compute_snapshot(portfolio["id"], forecast_year=2046, scenario_tag="BASE")

    # 2029: storage at 3 cycles (1.00) + DR before the step (0.85).
    assert snap_2029["accredited_supply_mw"] == pytest.approx(134.50, abs=0.005)
    # 2030: storage at 4 cycles (1.00); DR steps up to 1.00.
    assert snap_2030["accredited_supply_mw"] == pytest.approx(145.00, abs=0.005)
    # 2045: storage at 19 cycles (1.00) + DR at 1.00.
    assert snap_2045["accredited_supply_mw"] == pytest.approx(145.00, abs=0.005)
    # 2046: storage crosses the 20-cycle cliff (0.75); DR stays at 1.00.
    assert snap_2046["accredited_supply_mw"] == pytest.approx(126.25, abs=0.005)


def test_accreditation_decided_inclusive_variant(api):
    """PRD §3.5: "A fleet unit contributes its `nameplate_mw` when it is `ACTIVE`, or
    when it is `DECIDED` and the snapshot's `forecast_year` is strictly earlier than its
    `retirement_year`; otherwise it contributes zero."
    PRD §3.5: "Under the `DECIDED_INCLUSIVE` accreditation mode, a `DECIDED` unit
    instead counts at full nameplate for every forecast year — the retirement decision
    is ignored — so the same fleet data yields a higher accredited supply and brackets
    the reliability outcome from above."

    Design: Corner/calculations/accreditation_decided_inclusive_variant
    """
    plan = create_plan(plan_name="IRP AccM", cycle_year=2026, planning_horizon_years=15)
    add_forecast(plan["id"], scenario_tag="BASE", forecast_year=2030, residential_mw=10)
    portfolio = add_portfolio(plan["id"], portfolio_name="PF-AccM", preferred_flag=True)
    resource = register_resource(unit_name="COAL-ACCM", resource_type="COAL",
                                 nameplate_mw=500, in_service_year=2010, fuel_type="COAL")
    retire_resource(resource["id"], retirement_year=2028, plan_id=plan["id"])

    exclusive = compute_snapshot(portfolio["id"], forecast_year=2030, scenario_tag="BASE")
    assert exclusive["accredited_supply_mw"] == pytest.approx(0.00, abs=0.005)

    # A (portfolio, forecast_year) pair hosts at most one snapshot (PRD §3.5), so the
    # DECIDED_INCLUSIVE bracket runs on a sibling portfolio over identical fleet data.
    portfolio_inc = add_portfolio(plan["id"], portfolio_name="PF-AccM-Inc",
                                  preferred_flag=False)
    inclusive = compute_snapshot(
        portfolio_inc["id"], forecast_year=2030, scenario_tag="BASE",
        accreditation_mode="DECIDED_INCLUSIVE",
    )
    assert inclusive["accredited_supply_mw"] == pytest.approx(450.00, abs=0.005)


def _setup_sensitivity_portfolio(plan_name, positions):
    """DRAFT plan + preferred portfolio with the given (candidate_kwargs, mw) positions
    and a 2031 BASE snapshot. Returns (plan, snapshot)."""
    plan = create_plan(plan_name=plan_name, cycle_year=2026, planning_horizon_years=15)
    add_forecast(plan["id"], scenario_tag="BASE", forecast_year=2031, residential_mw=10)
    portfolio = add_portfolio(plan["id"], preferred_flag=True)
    for candidate_kwargs, mw in positions:
        candidate = register_candidate(**candidate_kwargs)
        add_position(portfolio["id"], candidate["id"], committed_mw=mw)
    snapshot = compute_snapshot(portfolio["id"], forecast_year=2031, scenario_tag="BASE")
    return plan, snapshot


def test_sensitivity_policy_dimension_fossil_only(api):
    """PRD §3.7: "Under `POLICY`, only positions whose candidate's resource type is
    `COAL`, `GAS_CC`, or `GAS_CT` absorb the perturbation, at half strength: the
    adjusted score is the base cost of all other positions, unadjusted, plus the base
    cost of the fossil positions multiplied by one plus the product of a 0.5 policy
    factor and `delta_pct`."

    Design: Corner/calculations/sensitivity_policy_dimension_fossil_only
    """
    plan, snapshot = _setup_sensitivity_portfolio(
        "IRP Pol",
        [
            (dict(candidate_name="K-CT-POL", resource_type="GAS_CT", nameplate_mw=200,
                  online_year=2029, capex_usd_per_kw=700, fixed_om_usd_per_kw_year=12,
                  fuel_type="NATURAL_GAS", build_lead_years=2), 100),
            (dict(candidate_name="K-SOL-POL", resource_type="SOLAR", nameplate_mw=200,
                  online_year=2029, capex_usd_per_kw=900, fixed_om_usd_per_kw_year=10,
                  fuel_type="SUN", build_lead_years=2), 100),
        ],
    )

    resp = api.create_sensitivity(
        plan["id"],
        {"snapshot_id": snapshot["id"], "dimension": "POLICY", "delta_pct": 0.50},
        PLANNER,
    )
    analysis = validate_success(resp, expected_status=201)
    assert analysis["base_score_usd"] == 15929683
    assert analysis["adjusted_score_usd"] == 17731367


def test_sensitivity_technology_cost_scales_capex_only(api):
    """PRD §3.7: "Under `TECHNOLOGY_COST`, each position's capital term is scaled by one
    plus `delta_pct` while its fixed operating term is left unscaled."

    Design: Corner/calculations/sensitivity_technology_cost_scales_capex_only
    """
    plan, snapshot = _setup_sensitivity_portfolio(
        "IRP Tech",
        [
            (dict(candidate_name="K-TECH", resource_type="GAS_CC", nameplate_mw=500,
                  online_year=2029, capex_usd_per_kw=1200, fixed_om_usd_per_kw_year=15,
                  fuel_type="NATURAL_GAS", build_lead_years=3), 253.8),
        ],
    )

    resp = api.create_sensitivity(
        plan["id"],
        {"snapshot_id": snapshot["id"], "dimension": "TECHNOLOGY_COST", "delta_pct": 0.50},
        PLANNER,
    )
    analysis = validate_success(resp, expected_status=201)
    assert analysis["base_score_usd"] == 29941451
    assert analysis["adjusted_score_usd"] == 43008677


def test_auto_select_waterfall_ranks_and_tiebreaks(api):
    """PRD §3.9: "The set is ranked by screening levelized cost per megawatt ascending
    (the §3.6 engine at the delivery year), ties broken by `global_sequence_index`
    ascending. Allocation proceeds in rank order, each candidate contributing the lesser
    of the remaining need and its uncommitted nameplate. If the eligible set is empty or
    cannot cover the requested block, the issue is rejected with
    `ERR_NO_ELIGIBLE_CANDIDATE`. The first candidate in rank order to receive an
    allocation becomes the commitment's `candidate_id`."

    Design: Corner/calculations/auto_select_waterfall_ranks_and_tiebreaks
    """
    plan, _portfolio, _snapshot = setup_approved_plan(plan_name="IRP WF")
    # SOLAR is registered first (lower global_sequence_index) but is more expensive per
    # MW-year than the GAS_CT, so cost ranking — not creation order — picks the winner.
    register_candidate(candidate_name="K-WF-SOLAR", resource_type="SOLAR",
                       nameplate_mw=100, online_year=2028, capex_usd_per_kw=900,
                       fixed_om_usd_per_kw_year=10, fuel_type="SUN", build_lead_years=2)
    gas_ct = register_candidate(candidate_name="K-WF-CT", resource_type="GAS_CT",
                                nameplate_mw=200, online_year=2028, capex_usd_per_kw=700,
                                fixed_om_usd_per_kw_year=12, fuel_type="NATURAL_GAS",
                                build_lead_years=2)

    resp = api.create_commitment(
        plan["id"],
        {"committed_mw": 80, "solicitation_type": "RFP", "auto_select": True},
        PLANNER,
    )
    first = validate_success(resp, expected_status=201)
    assert first["candidate_id"] == gas_ct["id"]

    # Remaining pool: GAS_CT 120 + SOLAR 100 = 220 < 250 requested.
    resp = api.create_commitment(
        plan["id"],
        {"committed_mw": 250, "solicitation_type": "RFP", "auto_select": True},
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_NO_ELIGIBLE_CANDIDATE)


def test_retirement_recommendation_strictly_positive_boundary(api):
    """PRD §3.6: "When the benefit is strictly positive the analysis `recommendation` is
    `RETIRE`; when it is zero or negative the recommendation is `KEEP` — an exactly-zero
    benefit recommends keeping the unit."
    PRD §3.6: "Combustion-turbine gas carries a flat $6,000 per MW-year; all other
    resource types carry no scheduled compliance cost."

    Design: Corner/calculations/retirement_recommendation_zero_boundary_keep
    """
    plan = create_plan(plan_name="IRP Zero2", cycle_year=2026, planning_horizon_years=15)
    add_forecast(plan["id"], scenario_tag="BASE", forecast_year=2028, residential_mw=10)
    portfolio = add_portfolio(plan["id"], portfolio_name="PF-Z2", preferred_flag=True)
    resource = register_resource(unit_name="CT-TINY", resource_type="GAS_CT",
                                 nameplate_mw=1, in_service_year=2000,
                                 fuel_type="NATURAL_GAS")
    register_candidate(candidate_name="K-CT-RA", resource_type="GAS_CT", nameplate_mw=200,
                       online_year=2027, capex_usd_per_kw=700,
                       fixed_om_usd_per_kw_year=12, fuel_type="NATURAL_GAS",
                       build_lead_years=2)
    retire_resource(resource["id"], retirement_year=2028, plan_id=plan["id"])
    snapshot = compute_snapshot(portfolio["id"], forecast_year=2028, scenario_tag="BASE")

    resp = api.create_retirement_analysis(
        resource["id"], {"plan_id": plan["id"], "snapshot_id": snapshot["id"]}, PLANNER
    )
    analysis = validate_success(resp, expected_status=201)

    # 6,000 $/MW-yr flat for GAS_CT x 1 MW x 10 window years.
    assert analysis["compliance_cost_usd"] == 60000
    # 14,000 $/MW-yr for GAS_CT x 1 MW x 10 window years.
    assert analysis["fixed_om_avoided_usd"] == 140000
    # Replacement cost dwarfs the avoided streams, so the net benefit is negative and
    # the strict > 0 rule recommends keeping the unit.
    assert analysis["net_retirement_benefit_usd"] == (
        analysis["compliance_cost_usd"]
        + analysis["fixed_om_avoided_usd"]
        - analysis["replacement_cost_usd"]
    )
    assert analysis["net_retirement_benefit_usd"] < 0
    assert analysis["recommendation"] == "KEEP"
