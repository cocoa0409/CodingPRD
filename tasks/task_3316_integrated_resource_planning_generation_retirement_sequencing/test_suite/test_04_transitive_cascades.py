"""Depth-3 transitive cascades: retire -> flag -> review block; award -> discharge -> report (PRD §3.4, §3.8, §3.9, §3.11)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_forecast,
    add_portfolio,
    commission_review,
    compute_snapshot,
    create_plan,
    get_portfolio_version,
    issue_commitment,
    list_plan_conditions,
    register_candidate,
    register_resource,
    retire_resource,
    set_clock,
    setup_approved_plan,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_AUG_01, CLOCK_AUG_31
from test_helpers.fixtures import PLANNER, drive_plan_to_under_review
from test_helpers.test_users import make_commissioner_headers


def _setup_cascade_plan_with_flagged_snapshot():
    """Plan whose preferred portfolio's 2030 snapshot passed (550 MW COAL unit,
    in service 2020, against load 400: 550 * 0.90 - 400 * 1.15 = +35), then was
    retire-flagged by retiring that unit (retirement_year 2028) while the plan was
    still DRAFT — retire against a non-DRAFT plan is ERR_PLAN_NOT_DRAFT (PRD §3.4).
    Returns (plan, portfolio, resource) with the plan still DRAFT."""
    set_clock(CLOCK_AUG_01)
    plan = create_plan(plan_name="IRP Casc", cycle_year=2026, planning_horizon_years=15)
    add_forecast(plan["id"], scenario_tag="BASE", forecast_year=2030, residential_mw=400)
    add_forecast(plan["id"], scenario_tag="HIGH_ELECTRIFICATION", forecast_year=2030,
                 residential_mw=400)
    portfolio = add_portfolio(plan["id"], portfolio_name="PF-Casc", preferred_flag=True)
    resource = register_resource(unit_name="COAL-CASC", resource_type="COAL",
                                 nameplate_mw=550, in_service_year=2020, fuel_type="COAL")
    snapshot = compute_snapshot(portfolio["id"], forecast_year=2030, scenario_tag="BASE")
    assert snapshot["meets_requirement"] is True, (
        f"Setup failed: baseline snapshot must pass: {snapshot}"
    )
    # Retire while the plan is DRAFT (PRD §3.4): retirement_year 2028 <= the
    # snapshot's forecast_year 2030, so the snapshot is retire-flagged.
    retire_resource(resource["id"], retirement_year=2028, plan_id=plan["id"])
    return plan, portfolio, resource


def test_retire_stales_snapshot_blocks_review(api):
    """PRD §3.4: "The decision then cascades through the deciding plan: for every
    portfolio under that plan, the portfolio's `version` increments by 1, and every
    reliability snapshot of those portfolios whose `forecast_year` is greater than or
    equal to the retirement year is retire-flagged."
    PRD §3.8: "For either approving decision, the preferred portfolio must present at
    least one snapshot with `meets_requirement` true that is not retire-flagged; without
    one the decision is rejected with `ERR_RELIABILITY_NOT_MET` (HTTP 422)."

    Design: Difficulty/transitive_cascade/retire_stales_snapshot_blocks_review
    """
    plan, portfolio, resource = _setup_cascade_plan_with_flagged_snapshot()
    pf_version_before = get_portfolio_version(portfolio["id"])

    drive_plan_to_under_review(plan["id"])

    # The retire cascade bumped the portfolio version (PRD §3.4) even though the
    # portfolio is now FROZEN.
    pf_version_after = get_portfolio_version(portfolio["id"])
    assert pf_version_after > pf_version_before

    # Recompute on the FROZEN portfolio is allowed; with the unit DECIDED and
    # 2030 >= 2028 it contributes zero, so the recomputed snapshot fails.
    recomputed = compute_snapshot(portfolio["id"], forecast_year=2030,
                                  scenario_tag="HIGH_ELECTRIFICATION")
    assert recomputed["accredited_supply_mw"] == pytest.approx(0.00, abs=0.005)
    assert recomputed["capacity_margin_mw"] == pytest.approx(-460.00, abs=0.005)
    assert recomputed["meets_requirement"] is False

    resp = commission_review(plan["id"], "APPROVE")
    validate_error(resp, ApiErrorId.ERR_RELIABILITY_NOT_MET)


def test_retire_flagged_slot_accepts_replacement_snapshot(api):
    """PRD §3.4: "A retire-flagged snapshot has two defining properties: it cannot
    satisfy the reliability precondition of commission review (§3.8), and it no longer
    occupies its `(portfolio_id, forecast_year)` uniqueness slot, so computing a fresh
    snapshot for the same slot replaces the flagged row rather than colliding with it —
    the fresh row carries no flag."
    PRD §3.5: "Snapshot compute is allowed while the portfolio is `DRAFT` or `FROZEN` —
    recompute-after-flag is precisely how a frozen portfolio's snapshots are refreshed
    after a retirement cascade — even though position add and remove are restricted to
    `DRAFT`."

    Design: Difficulty/transitive_cascade/retire_stales_snapshot_blocks_review
    """
    plan, portfolio, resource = _setup_cascade_plan_with_flagged_snapshot()
    drive_plan_to_under_review(plan["id"])

    # The retire-flagged (portfolio, 2030) slot accepts a replacement recompute even
    # though the portfolio is FROZEN; without the flag the same slot would collide.
    resp = api.create_snapshot(
        portfolio["id"],
        {"forecast_year": 2030, "scenario_tag": "HIGH_ELECTRIFICATION",
         "fuel_price_usd_per_mmbtu": 4.00,
         "expected_portfolio_version": get_portfolio_version(portfolio["id"])},
        PLANNER,
    )
    replacement = validate_success(resp, expected_status=201)
    assert replacement["meets_requirement"] is False
    assert replacement["accredited_supply_mw"] == pytest.approx(0.00, abs=0.005)


def _setup_condition_plan():
    """APPROVED_WITH_CONDITIONS plan with one OPEN condition (100 MW), a 300 MW
    candidate, and a 100 MW ISSUED commitment listing the condition."""
    conditions = [{"description": "Procure 100 MW solar", "required_procurement_mw": 100}]
    plan, portfolio, snapshot = setup_approved_plan(
        plan_name="IRP Casc2", forecast_year=2031, load_mw=400, conditions=conditions,
        extra_forecast_years=(2032,),
    )
    # The deviation report for 2032 reads the snapshot of the approved snapshot's
    # portfolio for 2032; snapshot compute is allowed on the FROZEN portfolio.
    compute_snapshot(portfolio["id"], forecast_year=2032, scenario_tag="BASE")
    condition = list_plan_conditions(plan["id"])[0]
    candidate = register_candidate(
        candidate_name="K-SOLAR", resource_type="SOLAR", nameplate_mw=300,
        online_year=2028, capex_usd_per_kw=900, fixed_om_usd_per_kw_year=10,
        fuel_type="SUN", build_lead_years=2,
    )
    commitment = issue_commitment(plan["id"], candidate_id=candidate["id"],
                                  committed_mw=100, solicitation_type="RFP",
                                  condition_discharge_ids=[condition["id"]])
    return plan, condition, commitment


def test_award_discharges_condition_shrinks_report_shortfall(api):
    """PRD §3.9: "On award, each listed condition that is still `OPEN` transitions to
    `DISCHARGED`, its `version` bumping by 1, and the commitment's own `version` bumps
    by 1."
    PRD §3.11: "the `required_procurement_mw` sums the demand of the plan's conditions
    still `OPEN`; and the `procurement_deviation_mw` is the former minus the latter,
    carried to 2 decimal places, with a negative value meaning the plan is short of its
    conditions."

    Design: Difficulty/transitive_cascade/award_discharges_condition_shrinks_report_shortfall
    """
    plan, condition, commitment = _setup_condition_plan()

    # Pre-award 2031 report: the ISSUED commitment counts as committed; the OPEN
    # condition counts as required.
    resp = api.create_deviation_report(
        plan["id"], {"report_year": 2031, "actual_load_mw": 400}, PLANNER
    )
    pre = validate_success(resp, expected_status=201)
    assert pre["committed_procurement_mw"] == pytest.approx(100, abs=0.005)
    assert pre["required_procurement_mw"] == pytest.approx(100, abs=0.005)
    assert pre["procurement_deviation_mw"] == pytest.approx(0.00, abs=0.005)

    award = validate_success(
        api.award_commitment(commitment["id"], make_commissioner_headers("commissioner-aw-1"))
    )
    assert award["status"] == "AWARDED"

    condition_after = list_plan_conditions(plan["id"])[0]
    assert condition_after["id"] == condition["id"]
    assert condition_after["status"] == "DISCHARGED"
    assert condition_after["version"] == condition["version"] + 1

    # Post-award 2032 report: the discharge (proximate cause), not the award itself,
    # removes the requirement, so the deviation flips from 0 to +100.
    resp = api.create_deviation_report(
        plan["id"], {"report_year": 2032, "actual_load_mw": 400}, PLANNER
    )
    post = validate_success(resp, expected_status=201)
    assert post["required_procurement_mw"] == pytest.approx(0, abs=0.005)
    assert post["procurement_deviation_mw"] == pytest.approx(100.00, abs=0.005)


def test_award_discharge_moves_required_sum_to_zero(api):
    """PRD §3.9: "On award, each listed condition that is still `OPEN` transitions to
    `DISCHARGED`, its `version` bumping by 1, and the commitment's own `version` bumps
    by 1."
    PRD §3.11: "The `committed_procurement_mw` sums `committed_mw` over the plan's
    commitments in `ISSUED` or `AWARDED` status; the `required_procurement_mw` sums the
    demand of the plan's conditions still `OPEN`; and the `procurement_deviation_mw` is
    the former minus the latter, carried to 2 decimal places, with a negative value
    meaning the plan is short of its conditions."

    Design: Difficulty/transitive_cascade/award_discharges_condition_shrinks_report_shortfall
    """
    plan, condition, commitment = _setup_condition_plan()

    validate_success(
        api.award_commitment(commitment["id"], make_commissioner_headers("commissioner-aw-2"))
    )

    resp = api.create_deviation_report(
        plan["id"], {"report_year": 2032, "actual_load_mw": 400}, PLANNER
    )
    post = validate_success(resp, expected_status=201)
    # The AWARDED commitment still counts as committed; the DISCHARGED condition no
    # longer counts as required.
    assert post["committed_procurement_mw"] == pytest.approx(100, abs=0.005)
    assert post["required_procurement_mw"] == pytest.approx(0, abs=0.005)
    assert post["procurement_deviation_mw"] == pytest.approx(100.00, abs=0.005)
    # No negative arm: with load matching the baseline, no material breach.
    assert post["material_breach"] is False
