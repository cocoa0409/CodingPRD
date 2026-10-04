"""Composite setup helpers.

Every fixture builds its preconditions from scratch using only PRD-declared
endpoints: the test harness restarts the server (empty database) before every
test, so no state is shared between tests.

Setup calls use get_success_data() so failures surface as clear setup errors.
"""
from datetime import date as _date

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import (
    CLOCK_AUG_01,
    CLOCK_AUG_31,
    CLOCK_DEFAULT,
    DEFAULT_FUEL_PRICE,
)
from .factories import (
    create_candidate_payload,
    create_comment_payload,
    create_forecast_payload,
    create_intervenor_payload,
    create_plan_payload,
    create_portfolio_payload,
    create_resource_payload,
    create_testimony_payload,
)
from .test_users import TEST_USERS, make_intervener_headers

PLANNER = TEST_USERS["planner_headers"]
COMMISSIONER = TEST_USERS["commissioner_headers"]
ADMIN = TEST_USERS["admin_headers"]
COMMENTER = TEST_USERS["commenter_headers"]


# ---------------------------------------------------------------------------
# Low-level building blocks
# ---------------------------------------------------------------------------

# Tracks the last instant pushed through set_clock within the current test so
# multi-plan fixtures can keep the logical clock moving forward (the PRD's clock
# narratives only describe forward motion; several lifecycle gates compare
# against it).
_CLOCK_STATE = {"current": _date(2026, 9, 1)}


def _current_clock_date() -> _date:
    return _CLOCK_STATE["current"]


def set_clock(to_iso8601: str):
    """Drive the server logical clock (PRD §2.4)."""
    _CLOCK_STATE["current"] = _date.fromisoformat(to_iso8601[:10])
    resp = api_client.set_clock({"to_iso8601": to_iso8601}, PLANNER)
    return get_success_data(resp)


def create_plan(plan_name="IRP Plan", cycle_year=2026, planning_horizon_years=15):
    payload = create_plan_payload(
        plan_name=plan_name,
        cycle_year=cycle_year,
        planning_horizon_years=planning_horizon_years,
    )
    return get_success_data(api_client.create_plan(payload, PLANNER))


def add_forecast(plan_id, scenario_tag="BASE", forecast_year=2030, **class_mw):
    payload = create_forecast_payload(
        scenario_tag=scenario_tag, forecast_year=forecast_year, **class_mw
    )
    return get_success_data(api_client.create_forecast(plan_id, payload, PLANNER))


def add_portfolio(plan_id, portfolio_name=None, preferred_flag=None):
    overrides = {}
    if portfolio_name is not None:
        overrides["portfolio_name"] = portfolio_name
    if preferred_flag is not None:
        overrides["preferred_flag"] = preferred_flag
    return get_success_data(
        api_client.create_portfolio(plan_id, create_portfolio_payload(**overrides), PLANNER)
    )


def register_resource(unit_name=None, **overrides):
    if unit_name is not None:
        overrides["unit_name"] = unit_name
    return get_success_data(api_client.create_resource(create_resource_payload(**overrides), PLANNER))


def register_candidate(candidate_name=None, **overrides):
    if candidate_name is not None:
        overrides["candidate_name"] = candidate_name
    return get_success_data(api_client.create_candidate(create_candidate_payload(**overrides), PLANNER))


def add_position(portfolio_id, candidate_id, committed_mw):
    return get_success_data(
        api_client.add_position(
            portfolio_id, {"candidate_id": candidate_id, "committed_mw": committed_mw}, PLANNER
        )
    )


def compute_snapshot(portfolio_id, forecast_year, scenario_tag="BASE",
                     fuel_price=DEFAULT_FUEL_PRICE, **extra):
    """Compute a snapshot, reading the portfolio's current version for the OCC guard."""
    pf = get_success_data(api_client.get_portfolio(portfolio_id, PLANNER))
    payload = {
        "forecast_year": forecast_year,
        "scenario_tag": scenario_tag,
        "fuel_price_usd_per_mmbtu": fuel_price,
        "expected_portfolio_version": pf["version"],
    }
    payload.update(extra)
    return get_success_data(api_client.create_snapshot(portfolio_id, payload, PLANNER))


def retire_resource(resource_id, retirement_year, plan_id):
    return get_success_data(
        api_client.retire_resource(
            resource_id, {"retirement_year": retirement_year, "plan_id": plan_id}, PLANNER
        )
    )


def get_portfolio_version(portfolio_id) -> int:
    return get_success_data(api_client.get_portfolio(portfolio_id, PLANNER))["version"]


def get_plan(plan_id):
    return get_success_data(api_client.get_plan(plan_id, PLANNER))


# ---------------------------------------------------------------------------
# Tier 1: plan state progression
# ---------------------------------------------------------------------------

def create_draft_plan_with_basics(plan_name="IRP Plan", cycle_year=2026,
                                  forecast_year=2030, residential_mw=10,
                                  preferred=True, planning_horizon_years=15):
    """DRAFT plan + one BASE forecast + one portfolio. Returns (plan, portfolio)."""
    plan = create_plan(plan_name=plan_name, cycle_year=cycle_year,
                       planning_horizon_years=planning_horizon_years)
    add_forecast(plan["id"], scenario_tag="BASE", forecast_year=forecast_year,
                 residential_mw=residential_mw)
    portfolio = add_portfolio(plan["id"], preferred_flag=preferred)
    return plan, portfolio


def open_plan_for_comment(plan_id):
    return get_success_data(api_client.open_comment(plan_id, PLANNER))


def submit_plan_for_review(plan_id):
    return get_success_data(api_client.submit_for_review(plan_id, PLANNER))


def drive_plan_to_under_review(plan_id, clock_submit_date=CLOCK_AUG_31):
    """OPEN_FOR_COMMENT -> UNDER_REVIEW after advancing the clock past the window."""
    open_plan_for_comment(plan_id)
    set_clock(clock_submit_date)
    return submit_plan_for_review(plan_id)


def commission_review(plan_id, decision, expected_plan_version=None, conditions=None,
                      headers=COMMISSIONER):
    if expected_plan_version is None:
        expected_plan_version = get_plan(plan_id)["version"]
    payload = {"decision": decision, "expected_plan_version": expected_plan_version}
    if conditions is not None:
        payload["conditions"] = conditions
    return api_client.commission_review(plan_id, payload, headers)


def setup_plan_under_review(plan_name="IRP Review", cycle_year=2026, forecast_year=2030,
                            residential_mw=10, preferred=True, start_clock=CLOCK_AUG_01,
                            planning_horizon_years=15):
    """Plan driven to UNDER_REVIEW. Returns (plan_dict_refreshed, portfolio).

    Side effect: leaves the logical clock at the submit date (window closed).
    """
    set_clock(start_clock)
    plan, portfolio = create_draft_plan_with_basics(
        plan_name=plan_name, cycle_year=cycle_year, forecast_year=forecast_year,
        residential_mw=residential_mw, preferred=preferred,
        planning_horizon_years=planning_horizon_years,
    )
    drive_plan_to_under_review(plan["id"])
    return get_plan(plan["id"]), portfolio


def setup_plan_rejected(plan_name="IRP Rej", cycle_year=2026, forecast_year=2030,
                        residential_mw=10, preferred=True, start_clock=CLOCK_AUG_01):
    """Plan driven UNDER_REVIEW then REJECTED. Returns (plan, portfolio)."""
    plan, portfolio = setup_plan_under_review(
        plan_name=plan_name, cycle_year=cycle_year, forecast_year=forecast_year,
        residential_mw=residential_mw, preferred=preferred, start_clock=start_clock,
    )
    resp = commission_review(plan["id"], "REJECT")
    assert resp.status_code == 200, f"Setup failed: REJECT review -> {resp.text}"
    return get_plan(plan["id"]), portfolio


def setup_approved_plan(plan_name="IRP App", cycle_year=2026, forecast_year=2031,
                        load_mw=400, conditions=None, start_clock=CLOCK_AUG_01,
                        portfolio_name=None, planning_horizon_years=15,
                        extra_forecast_years=()):
    """Full lifecycle to APPROVED (or APPROVED_WITH_CONDITIONS when conditions given).

    Reliability is met by a 1150 MW SOLAR fleet unit (accredited 460.00) against the
    given coincident load: 460.00 - load * 1.15 >= 0 for load <= 400.
    `extra_forecast_years` adds BASE rows for additional years (same per-class load),
    needed when later steps compute snapshots for years other than `forecast_year`.
    Returns (plan, portfolio, snapshot).
    """
    set_clock(start_clock)
    plan = create_plan(plan_name=plan_name, cycle_year=cycle_year,
                       planning_horizon_years=planning_horizon_years)
    for year in (forecast_year, *extra_forecast_years):
        add_forecast(plan["id"], scenario_tag="BASE", forecast_year=year,
                     residential_mw=load_mw)
    portfolio = add_portfolio(plan["id"], portfolio_name=portfolio_name, preferred_flag=True)
    register_resource(resource_type="SOLAR", nameplate_mw=1150, in_service_year=2020,
                      fuel_type="SUN")
    snapshot = compute_snapshot(portfolio["id"], forecast_year=forecast_year)
    assert snapshot["meets_requirement"] is True, (
        f"Setup failed: reliability snapshot does not meet requirement: {snapshot}"
    )
    drive_plan_to_under_review(plan["id"])
    decision = "APPROVE_WITH_CONDITIONS" if conditions else "APPROVE"
    resp = commission_review(plan["id"], decision, conditions=conditions)
    assert resp.status_code == 200, f"Setup failed: commission review -> {resp.text}"
    return get_plan(plan["id"]), portfolio, snapshot


# ---------------------------------------------------------------------------
# Tier 2: stakeholder helpers
# ---------------------------------------------------------------------------

def register_intervenor(legal_name=None, party_type="CONSUMER_ADVOCATE", standing_approved=None):
    overrides = {"party_type": party_type}
    if legal_name is not None:
        overrides["legal_name"] = legal_name
    if standing_approved is not None:
        overrides["standing_approved"] = standing_approved
    return get_success_data(
        api_client.create_intervenor(create_intervenor_payload(**overrides), ADMIN)
    )


def file_testimony(plan_id, intervenor_id, topic="Load forecast", body=None):
    """File testimony with the intervenor acting as itself (ownership identity)."""
    payload = create_testimony_payload(intervenor_id, topic=topic)
    if body is not None:
        payload["body"] = body
    return get_success_data(
        api_client.create_testimony(plan_id, payload, make_intervener_headers(intervenor_id))
    )


def file_comment(plan_id, **overrides):
    return get_success_data(
        api_client.create_comment(plan_id, create_comment_payload(**overrides), COMMENTER)
    )


# ---------------------------------------------------------------------------
# Tier 3: procurement helpers
# ---------------------------------------------------------------------------

def issue_commitment(plan_id, candidate_id=None, committed_mw=50, solicitation_type="RFP",
                     condition_discharge_ids=None, auto_select=None, headers=PLANNER):
    payload = {"committed_mw": committed_mw, "solicitation_type": solicitation_type}
    if candidate_id is not None:
        payload["candidate_id"] = candidate_id
    if condition_discharge_ids is not None:
        payload["condition_discharge_ids"] = condition_discharge_ids
    if auto_select is not None:
        payload["auto_select"] = auto_select
    return get_success_data(api_client.create_commitment(plan_id, payload, headers))


def list_plan_conditions(plan_id):
    resp = api_client.list_conditions(plan_id, PLANNER)
    assert resp.status_code == 200, f"Setup failed: list conditions -> {resp.text}"
    return resp.json()["data"]
