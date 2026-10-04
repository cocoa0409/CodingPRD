"""Endpoint corners: typed 404s, OCC guards, computed deviation reads, FK listings (PRD §2.6, §2.8, §3.3, §3.11)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    TEST_USERS,
    add_forecast,
    add_portfolio,
    add_position,
    compute_snapshot,
    create_draft_plan_with_basics,
    create_plan,
    drive_plan_to_under_review,
    get_portfolio_version,
    get_success_data,
    register_candidate,
    register_resource,
    set_clock,
    setup_approved_plan,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import PLANNER

COMMISSIONER = TEST_USERS["commissioner_headers"]


def test_get_unknown_ids_return_typed_not_found(api):
    """PRD §2.8: "The full not-found family is `ERR_PLAN_NOT_FOUND`,
    `ERR_FORECAST_NOT_FOUND`, `ERR_PORTFOLIO_NOT_FOUND`, `ERR_RESOURCE_NOT_FOUND`,
    `ERR_CANDIDATE_NOT_FOUND`, `ERR_SNAPSHOT_NOT_FOUND`, `ERR_ANALYSIS_NOT_FOUND`,
    `ERR_COMMENT_NOT_FOUND`, `ERR_TESTIMONY_NOT_FOUND`, `ERR_INTERVENOR_NOT_FOUND`,
    `ERR_COMMITMENT_NOT_FOUND`, and `ERR_CONDITION_NOT_FOUND`; each is HTTP 404."

    Design: Corner/endpoints/get_unknown_ids_return_typed_not_found
    """
    resp = api.get_resource(NON_EXISTENT_UUID, PLANNER)
    validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_FOUND)

    resp = api.get_candidate(NON_EXISTENT_UUID, PLANNER)
    validate_error(resp, ApiErrorId.ERR_CANDIDATE_NOT_FOUND)

    resp = api.get_commitment(NON_EXISTENT_UUID, PLANNER)
    validate_error(resp, ApiErrorId.ERR_COMMITMENT_NOT_FOUND)


def test_occ_stale_portfolio_version_on_snapshot(api):
    """PRD §2.6: "The snapshot-compute operation on a portfolio requires a non-optional
    `expected_portfolio_version` input carrying the client's last observed `version` of
    the portfolio. Retire and cancel-retirement cascades bump the `version` of every
    portfolio under the deciding plan (§3.4), so a snapshot computed against an older
    view would silently embed obsolete fleet state; when the supplied value does not
    match the portfolio's current `version`, the call is rejected with
    `ERR_STALE_PORTFOLIO_VERSION` (HTTP 412)."

    Design: Corner/endpoints/occ_stale_portfolio_version_on_snapshot
    """
    plan, portfolio = create_draft_plan_with_basics(plan_name="IRP OCC")
    candidate = register_candidate(candidate_name="K-OCC")
    # A position add bumps the portfolio version from 1 to 2.
    add_position(portfolio["id"], candidate["id"], committed_mw=30)
    assert get_portfolio_version(portfolio["id"]) == 2

    stale_payload = {
        "forecast_year": 2030, "scenario_tag": "BASE",
        "fuel_price_usd_per_mmbtu": 4.00, "expected_portfolio_version": 1,
    }
    resp = api.create_snapshot(portfolio["id"], stale_payload, PLANNER)
    validate_error(resp, ApiErrorId.ERR_STALE_PORTFOLIO_VERSION)

    fresh_payload = dict(stale_payload, expected_portfolio_version=2)
    resp = api.create_snapshot(portfolio["id"], fresh_payload, PLANNER)
    validate_success(resp, expected_status=201)


def test_occ_stale_plan_version_on_commission_review(api):
    """PRD §2.6: "The commission-review operation on a plan requires a non-optional
    `expected_plan_version` input carrying the client's last observed `version` of the
    plan. If that value does not match the plan's current `version` at the moment of the
    call — because another review decision, a reopen, or a supersede cascade has
    advanced it since the client last read the plan — the call is rejected with
    `ERR_STALE_PLAN_VERSION` (HTTP 412)."

    Design: Corner/endpoints/occ_stale_plan_version_on_commission_review
    """
    set_clock("2026-08-01T00:00:00Z")
    plan = create_plan(plan_name="IRP OCC2", cycle_year=2026, planning_horizon_years=15)
    add_forecast(plan["id"], scenario_tag="BASE", forecast_year=2031, residential_mw=400)
    portfolio = add_portfolio(plan["id"], portfolio_name="PF-OCC2", preferred_flag=True)
    register_resource(resource_type="SOLAR", nameplate_mw=1150, in_service_year=2020,
                      fuel_type="SUN")
    compute_snapshot(portfolio["id"], forecast_year=2031, scenario_tag="BASE")

    # Capture the plan version at OPEN_FOR_COMMENT; submit-for-review then bumps it.
    resp = api.open_comment(plan["id"], PLANNER)
    stale_version = validate_success(resp)["version"]
    set_clock("2026-08-31T00:00:00Z")
    fresh_version = validate_success(api.submit_for_review(plan["id"], PLANNER))["version"]
    assert fresh_version == stale_version + 1

    resp = api.commission_review(
        plan["id"], {"decision": "APPROVE", "expected_plan_version": stale_version},
        COMMISSIONER,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_PLAN_VERSION)

    resp = api.commission_review(
        plan["id"], {"decision": "APPROVE", "expected_plan_version": fresh_version},
        COMMISSIONER,
    )
    approved = validate_success(resp)
    assert approved["status"] == "APPROVED"


def test_computed_read_deviation_report_fields(api):
    """PRD §3.11: "The report's baseline is `baseline_load_mw`: the modeled load for
    `report_year` taken from the plan's approved snapshot, or — when that snapshot
    covers a different year — from the snapshot of the approved snapshot's portfolio for
    `report_year`."
    PRD §3.11: "A report is a `material_breach` when either measure trips its wire: the
    absolute load deviation is strictly greater than five percent — an exactly 0.0500
    deviation is not a breach — or the procurement deviation is strictly negative."

    Design: Corner/endpoints/computed_read_deviation_report_fields
    """
    plan, _portfolio, _snapshot = setup_approved_plan(
        plan_name="IRP Dev", forecast_year=2031, load_mw=400,
        conditions=[{"description": "Procure 50 MW", "required_procurement_mw": 50}],
    )

    resp = api.create_deviation_report(
        plan["id"], {"report_year": 2031, "actual_load_mw": 421}, PLANNER
    )
    report = validate_success(resp, expected_status=201)

    assert report["baseline_load_mw"] == pytest.approx(400.00, abs=0.005)
    assert report["load_deviation_pct"] == pytest.approx(0.0525, abs=0.00005)
    assert report["committed_procurement_mw"] == pytest.approx(0, abs=0.005)
    assert report["required_procurement_mw"] == pytest.approx(50, abs=0.005)
    assert report["procurement_deviation_mw"] == pytest.approx(-50.00, abs=0.005)
    # Both arms trip: |0.0525| > 0.05 and the procurement deviation is negative.
    assert report["material_breach"] is True


def test_fk_reverse_reachability_lists(api):
    """PRD §3.3: "Positions are listable per portfolio (filterable by `selected`), per
    candidate, and across portfolios with `portfolio_id` and `candidate_id` filters, and
    a single position is retrievable by id."

    Design: Corner/endpoints/fk_reverse_reachability_lists
    """
    plan = create_plan(plan_name="IRP FK")
    portfolio = add_portfolio(plan["id"], portfolio_name="PF-FK")
    candidate1 = register_candidate(candidate_name="K-FK1")
    candidate2 = register_candidate(candidate_name="K-FK2", resource_type="WIND",
                                    nameplate_mw=50, online_year=2029,
                                    capex_usd_per_kw=1100, fixed_om_usd_per_kw_year=20,
                                    fuel_type="WIND", build_lead_years=2)
    position = add_position(portfolio["id"], candidate1["id"], committed_mw=30)

    data, meta = validate_paginated(api.list_positions(portfolio["id"], PLANNER))
    assert [row["id"] for row in data] == [position["id"]]

    data, meta = validate_paginated(api.list_candidate_positions(candidate1["id"], PLANNER))
    assert [row["id"] for row in data] == [position["id"]]

    data, meta = validate_paginated(api.list_candidate_positions(candidate2["id"], PLANNER))
    assert data == []
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
