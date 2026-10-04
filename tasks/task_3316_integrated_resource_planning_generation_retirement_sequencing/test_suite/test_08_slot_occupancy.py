"""Slot occupancy semantics: snapshot years vs deviation report years (PRD §3.5, §3.11)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_forecast,
    add_portfolio,
    compute_snapshot,
    create_plan,
    get_portfolio_version,
    register_resource,
    retire_resource,
    set_clock,
    setup_approved_plan,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import PLANNER


def test_duplicate_snapshot_rejected_then_replaced_after_retire_flag(api):
    """PRD §3.5: "Each `(portfolio_id, forecast_year)` pair hosts at most one unflagged
    snapshot: computing into an occupied, unflagged slot is rejected with
    `ERR_DUPLICATE_SNAPSHOT` (HTTP 409), while a retire-flagged occupant (§3.4) is
    replaced by the recompute and its flag does not carry over."
    PRD §3.4: "A retire-flagged snapshot has two defining properties: it cannot satisfy
    the reliability precondition of commission review (§3.8), and it no longer occupies
    its `(portfolio_id, forecast_year)` uniqueness slot, so computing a fresh snapshot
    for the same slot replaces the flagged row rather than colliding with it — the
    fresh row carries no flag."

    Design: Difficulty/resource_temporal_overlap/duplicate_snapshot_year_interval_key
    """
    plan = create_plan(plan_name="IRP Over1", cycle_year=2026, planning_horizon_years=15)
    add_forecast(plan["id"], scenario_tag="BASE", forecast_year=2030, residential_mw=400)
    portfolio = add_portfolio(plan["id"], portfolio_name="PF-O1", preferred_flag=True)
    resource = register_resource(unit_name="COAL-O1", resource_type="COAL",
                                 nameplate_mw=500, in_service_year=2010, fuel_type="COAL")

    compute_snapshot(portfolio["id"], forecast_year=2030, scenario_tag="BASE")

    # Occupied and unflagged: the second compute collides.
    resp = api.create_snapshot(
        portfolio["id"],
        {"forecast_year": 2030, "scenario_tag": "BASE",
         "fuel_price_usd_per_mmbtu": 5.00,
         "expected_portfolio_version": get_portfolio_version(portfolio["id"])},
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SNAPSHOT)

    # A retire decision with retirement_year <= 2030 frees the slot.
    retire_resource(resource["id"], retirement_year=2028, plan_id=plan["id"])

    resp = api.create_snapshot(
        portfolio["id"],
        {"forecast_year": 2030, "scenario_tag": "BASE",
         "fuel_price_usd_per_mmbtu": 5.00,
         "expected_portfolio_version": get_portfolio_version(portfolio["id"])},
        PLANNER,
    )
    replacement = validate_success(resp, expected_status=201)
    # The DECIDED unit contributes zero for 2030 >= 2028 on the fresh row.
    assert replacement["accredited_supply_mw"] == pytest.approx(0.00, abs=0.005)


def test_snapshot_duplicate_and_replacement_are_distinct_rows(api):
    """PRD §3.5: "Each `(portfolio_id, forecast_year)` pair hosts at most one unflagged
    snapshot: computing into an occupied, unflagged slot is rejected with
    `ERR_DUPLICATE_SNAPSHOT` (HTTP 409), while a retire-flagged occupant (§3.4) is
    replaced by the recompute and its flag does not carry over."
    PRD §2.5: "A `ReliabilitySnapshot` is a computed, immutable artifact and likewise
    carries only `id` and `created_at`, with no `updated_at` or `version`; change is
    expressed by replacing the snapshot, not editing it."

    Design: Difficulty/resource_temporal_overlap/duplicate_snapshot_year_interval_key
    """
    plan = create_plan(plan_name="IRP Over1b", cycle_year=2026, planning_horizon_years=15)
    add_forecast(plan["id"], scenario_tag="BASE", forecast_year=2030, residential_mw=400)
    portfolio = add_portfolio(plan["id"], portfolio_name="PF-O1b", preferred_flag=True)
    resource = register_resource(unit_name="COAL-O1b", resource_type="COAL",
                                 nameplate_mw=500, in_service_year=2010, fuel_type="COAL")

    original = compute_snapshot(portfolio["id"], forecast_year=2030, scenario_tag="BASE")
    assert original["accredited_supply_mw"] == pytest.approx(450.00, abs=0.005)

    resp = api.create_snapshot(
        portfolio["id"],
        {"forecast_year": 2030, "scenario_tag": "BASE",
         "fuel_price_usd_per_mmbtu": 5.00,
         "expected_portfolio_version": get_portfolio_version(portfolio["id"])},
        PLANNER,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_SNAPSHOT)

    retire_resource(resource["id"], retirement_year=2028, plan_id=plan["id"])
    replacement = compute_snapshot(portfolio["id"], forecast_year=2030, scenario_tag="BASE")

    # Replacement, not edit: the fresh row is a distinct artifact for the same slot.
    assert replacement["id"] != original["id"]
    assert replacement["forecast_year"] == 2030
    assert replacement["accredited_supply_mw"] == pytest.approx(0.00, abs=0.005)
    assert "version" not in replacement


def test_duplicate_deviation_report_hard_occupancy(api):
    """PRD §3.11: "The plan must be in `APPROVED` or `APPROVED_WITH_CONDITIONS` status —
    otherwise `ERR_PLAN_NOT_APPROVED` — and one report per plan per year is the limit:
    a duplicate `(plan_id, report_year)` pair is rejected with `ERR_DUPLICATE_REPORT`
    (HTTP 409)."
    PRD §3.11: "Reports are immutable once filed, listable per plan or across plans by
    `plan_id`, and retrievable individually by id."

    Design: Difficulty/resource_temporal_overlap/deviation_report_year_collision_no_stale_exception
    """
    plan, _portfolio, _snapshot = setup_approved_plan(
        plan_name="IRP Over2", forecast_year=2031, load_mw=400,
    )

    resp = api.create_deviation_report(
        plan["id"], {"report_year": 2031, "actual_load_mw": 420}, PLANNER
    )
    validate_success(resp, expected_status=201)

    resp = api.create_deviation_report(
        plan["id"], {"report_year": 2031, "actual_load_mw": 430}, PLANNER
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPORT)


def test_deviation_report_for_other_year_accepted(api):
    """PRD §3.11: "The plan must be in `APPROVED` or `APPROVED_WITH_CONDITIONS` status —
    otherwise `ERR_PLAN_NOT_APPROVED` — and one report per plan per year is the limit:
    a duplicate `(plan_id, report_year)` pair is rejected with `ERR_DUPLICATE_REPORT`
    (HTTP 409)."
    PRD §3.11: "The report's baseline is `baseline_load_mw`: the modeled load for
    `report_year` taken from the plan's approved snapshot, or — when that snapshot
    covers a different year — from the snapshot of the approved snapshot's portfolio
    for `report_year`."

    Design: Difficulty/resource_temporal_overlap/deviation_report_year_collision_no_stale_exception
    """
    plan, portfolio, _snapshot = setup_approved_plan(
        plan_name="IRP Over2b", forecast_year=2031, load_mw=400,
        extra_forecast_years=(2032,),
    )
    # A snapshot for 2032 of the approved snapshot's portfolio supplies the baseline;
    # snapshot compute is allowed on the FROZEN portfolio.
    compute_snapshot(portfolio["id"], forecast_year=2032, scenario_tag="BASE")

    resp = api.create_deviation_report(
        plan["id"], {"report_year": 2031, "actual_load_mw": 400}, PLANNER
    )
    validate_success(resp, expected_status=201)

    # A different report_year is a different slot: no collision.
    resp = api.create_deviation_report(
        plan["id"], {"report_year": 2032, "actual_load_mw": 400}, PLANNER
    )
    report = validate_success(resp, expected_status=201)
    assert report["report_year"] == 2032

    # But the 2031 slot is now occupied: a repeat still collides.
    resp = api.create_deviation_report(
        plan["id"], {"report_year": 2031, "actual_load_mw": 410}, PLANNER
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_REPORT)
