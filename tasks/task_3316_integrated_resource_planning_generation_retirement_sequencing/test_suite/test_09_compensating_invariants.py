"""Compensating invariants: nameplate pool restore and fleet accreditation restore (PRD §3.4, §3.9)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_forecast,
    add_portfolio,
    compute_snapshot,
    create_plan,
    get_portfolio_version,
    issue_commitment,
    register_candidate,
    register_resource,
    retire_resource,
    setup_approved_plan,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import PLANNER


def test_cancel_restores_candidate_nameplate_pool(api):
    """PRD §3.9: "The aggregate committed megawatts per candidate across all commitments
    in `ISSUED` or `AWARDED` status must never exceed the candidate's `nameplate_mw`; an
    issue that would breach the cap is rejected with `ERR_NAMEPLATE_EXCEEDED`, and an
    issue naming a candidate with no feasible remaining capacity is rejected with
    `ERR_NO_ELIGIBLE_CANDIDATE` (HTTP 422)."
    PRD §3.9: "Cancelling instead moves `ISSUED → CANCELLED` at a planner's hand, frees
    the commitment's megawatts from the candidate's aggregate, and bumps the
    commitment's `version` — but only while every listed condition is still `OPEN`;
    cancelling a commitment whose listed condition has already been discharged would
    orphan the discharge and is rejected with `ERR_CONDITION_ALREADY_DISCHARGED`
    (HTTP 409)."

    Design: Difficulty/compensating_invariant/candidate_committed_mw_invariant
    """
    plan, _portfolio, _snapshot = setup_approved_plan(plan_name="IRP Inv1")
    candidate = register_candidate(
        candidate_name="K-INV", resource_type="GAS_CT", nameplate_mw=300,
        online_year=2028, capex_usd_per_kw=700, fixed_om_usd_per_kw_year=12,
        fuel_type="NATURAL_GAS", build_lead_years=2,
    )

    commitment = issue_commitment(plan["id"], candidate_id=candidate["id"],
                                  committed_mw=200)

    # 200 ISSUED + 150 requested > 300 nameplate: the pool is overdrawn.
    resp = api.create_commitment(
        plan["id"],
        {"candidate_id": candidate["id"], "committed_mw": 150,
         "solicitation_type": "RFP"},
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_NAMEPLATE_EXCEEDED)

    cancelled = validate_success(api.cancel_commitment(commitment["id"], PLANNER))
    assert cancelled["status"] == "CANCELLED"

    # The cancelled 200 is fully returned: the full 300 MW nameplate is issuable again.
    restored = issue_commitment(plan["id"], candidate_id=candidate["id"],
                                committed_mw=300, solicitation_type="SELF_BUILD")
    assert restored["status"] == "ISSUED"
    assert restored["committed_mw"] == pytest.approx(300, abs=0.005)


def test_overcommit_blocked_while_commitment_live(api):
    """PRD §3.9: "The aggregate committed megawatts per candidate across all commitments
    in `ISSUED` or `AWARDED` status must never exceed the candidate's `nameplate_mw`; an
    issue that would breach the cap is rejected with `ERR_NAMEPLATE_EXCEEDED`, and an
    issue naming a candidate with no feasible remaining capacity is rejected with
    `ERR_NO_ELIGIBLE_CANDIDATE` (HTTP 422)."

    Design: Difficulty/compensating_invariant/candidate_committed_mw_invariant
    """
    plan, _portfolio, _snapshot = setup_approved_plan(plan_name="IRP Inv1b")
    candidate = register_candidate(
        candidate_name="K-INV2", resource_type="GAS_CT", nameplate_mw=300,
        online_year=2028, capex_usd_per_kw=700, fixed_om_usd_per_kw_year=12,
        fuel_type="NATURAL_GAS", build_lead_years=2,
    )

    issue_commitment(plan["id"], candidate_id=candidate["id"], committed_mw=200)

    # While the 200 MW commitment stays ISSUED, even 101 MW more breaches the cap.
    resp = api.create_commitment(
        plan["id"],
        {"candidate_id": candidate["id"], "committed_mw": 101,
         "solicitation_type": "RFP"},
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_NAMEPLATE_EXCEEDED)

    # Exactly the remaining 100 MW is still issuable.
    top_up = issue_commitment(plan["id"], candidate_id=candidate["id"], committed_mw=100)
    assert top_up["status"] == "ISSUED"


def test_retire_cancel_restores_fleet_accreditation(api):
    """PRD §3.5: "A fleet unit contributes its `nameplate_mw` when it is `ACTIVE`, or
    when it is `DECIDED` and the snapshot's `forecast_year` is strictly earlier than its
    `retirement_year`; otherwise it contributes zero."
    PRD §3.4: "Or the planner may cancel the retirement, moving the unit
    `DECIDED → ACTIVE` and clearing `retirement_year`, `decision_year`, and `plan_id`.
    Cancellation is allowed only while the deciding plan is in `DRAFT` or `REJECTED`
    status — the simplified guarantee that no live procurement was justified by the
    decision — and is otherwise rejected with `ERR_PLAN_NOT_DRAFT`."

    Design: Difficulty/compensating_invariant/retirement_fleet_accreditation_invariant
    """
    plan = create_plan(plan_name="IRP Inv2", cycle_year=2026, planning_horizon_years=20)
    add_forecast(plan["id"], scenario_tag="BASE", forecast_year=2035, residential_mw=10)
    portfolio = add_portfolio(plan["id"], portfolio_name="PF-I2", preferred_flag=True)
    resource = register_resource(unit_name="COAL-INV", resource_type="COAL",
                                 nameplate_mw=300, in_service_year=1985, fuel_type="COAL")

    # Age 50 at 2035 hits the coal derate floor: 300 * 0.90 * 0.90 = 243.00.
    pre = compute_snapshot(portfolio["id"], forecast_year=2035, scenario_tag="BASE")
    assert pre["accredited_supply_mw"] == pytest.approx(243.00, abs=0.005)

    retire_resource(resource["id"], retirement_year=2031, plan_id=plan["id"])
    cancelled = validate_success(api.cancel_retirement(resource["id"], PLANNER))
    assert cancelled["status"] == "ACTIVE"
    assert cancelled["retirement_year"] is None
    assert cancelled["decision_year"] is None
    assert cancelled["plan_id"] is None

    # The retire-flagged 2035 slot accepts replacement; with the unit ACTIVE again the
    # recomputed row restores the exact pre-retire accredited supply — zero drift.
    post = compute_snapshot(portfolio["id"], forecast_year=2035, scenario_tag="BASE")
    assert post["accredited_supply_mw"] == pytest.approx(243.00, abs=0.005)


def test_retire_cancel_bumps_portfolio_version_twice(api):
    """PRD §3.4: "The decision then cascades through the deciding plan: for every
    portfolio under that plan, the portfolio's `version` increments by 1, and every
    reliability snapshot of those portfolios whose `forecast_year` is greater than or
    equal to the retirement year is retire-flagged."
    PRD §3.4: "Cancellation also cascades: the `version` of every portfolio under the
    former deciding plan increments by 1 alongside the unit's own bump."

    Design: Difficulty/compensating_invariant/retirement_fleet_accreditation_invariant
    """
    plan = create_plan(plan_name="IRP Inv2b", cycle_year=2026, planning_horizon_years=20)
    add_forecast(plan["id"], scenario_tag="BASE", forecast_year=2035, residential_mw=10)
    portfolio = add_portfolio(plan["id"], portfolio_name="PF-I2b", preferred_flag=True)
    resource = register_resource(unit_name="COAL-INV2", resource_type="COAL",
                                 nameplate_mw=300, in_service_year=1985, fuel_type="COAL")

    compute_snapshot(portfolio["id"], forecast_year=2035, scenario_tag="BASE")
    version_before = get_portfolio_version(portfolio["id"])

    retire_resource(resource["id"], retirement_year=2031, plan_id=plan["id"])
    version_after_retire = get_portfolio_version(portfolio["id"])
    assert version_after_retire == version_before + 1

    validate_success(api.cancel_retirement(resource["id"], PLANNER))
    version_after_cancel = get_portfolio_version(portfolio["id"])
    assert version_after_cancel == version_after_retire + 1

    # The pair's net effect on accreditation is zero: recompute restores 243.00.
    post = compute_snapshot(portfolio["id"], forecast_year=2035, scenario_tag="BASE")
    assert post["accredited_supply_mw"] == pytest.approx(243.00, abs=0.005)
