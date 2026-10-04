"""Cross-cutting cascades and immediate consistency (PRD §2.2, §2.4, §3.8)."""
import pytest

from test_helpers import (
    TEST_USERS,
    add_forecast,
    add_portfolio,
    api_client,
    commission_review,
    compute_snapshot,
    create_plan,
    get_plan,
    get_success_data,
    open_plan_for_comment,
    register_resource,
    set_clock,
    setup_plan_rejected,
    submit_plan_for_review,
    validate_success,
)
from test_helpers.constants import CLOCK_AUG_01, CLOCK_AUG_31, CLOCK_DEFAULT, CLOCK_OCT_01
from test_helpers.fixtures import PLANNER, _current_clock_date

COMMISSIONER = TEST_USERS["commissioner_headers"]


def _build_under_review_plan(name, cycle_year, forecast_year=2031, load=400):
    """Plan driven to UNDER_REVIEW with reliability met. Returns refreshed plan."""
    plan = create_plan(plan_name=name, cycle_year=cycle_year, planning_horizon_years=15)
    add_forecast(plan["id"], scenario_tag="BASE", forecast_year=forecast_year,
                 residential_mw=load)
    portfolio = add_portfolio(plan["id"], preferred_flag=True)
    register_resource(resource_type="SOLAR", nameplate_mw=1150, in_service_year=2020,
                      fuel_type="SUN")
    snapshot = compute_snapshot(portfolio["id"], forecast_year=forecast_year)
    assert snapshot["meets_requirement"] is True, f"Setup failed: {snapshot}"
    open_plan_for_comment(plan["id"])
    return plan, portfolio


def _open_and_submit(name, cycle_year):
    """Build a plan and drive it to UNDER_REVIEW on a lawful calendar: opened no
    earlier than Jan 1 of its cycle year (PRD §2.4 cycle deadline), submitted
    thirty days later, with the logical clock never moving backwards."""
    from datetime import date as _date, timedelta as _td
    open_date = max(_date(cycle_year, 1, 1), _current_clock_date())
    submit_date = open_date + _td(days=30)
    set_clock(f"{open_date.isoformat()}T00:00:00Z")
    plan, portfolio = _build_under_review_plan(name, cycle_year)
    set_clock(f"{submit_date.isoformat()}T00:00:00Z")
    submit_plan_for_review(plan["id"])
    return plan, portfolio


def test_approval_of_same_cycle_supersedes_prior_plan(api):
    """PRD §3.8: "Approval carries a cycle-wide side effect: when a plan reaches
    `APPROVED` or `APPROVED_WITH_CONDITIONS`, any other plan with the same `cycle_year`
    already in either approved state auto-transitions to `SUPERSEDED`, each superseded
    plan's `version` bumping by 1."

    Design: Corner/cross_cutting_layers/approval_of_same_cycle_supersedes_prior_plan
    """
    set_clock(CLOCK_AUG_01)
    plan_a, _pfa = _open_and_submit("IRP A", 2026)
    resp = commission_review(plan_a["id"], "APPROVE")
    assert resp.status_code == 200, f"Setup failed: {resp.text}"
    version_a_approved = get_plan(plan_a["id"])["version"]

    plan_b, _pfb = _open_and_submit("IRP B", 2026)

    plan_c, _pfc = _open_and_submit("IRP C", 2027)

    resp = commission_review(plan_b["id"], "APPROVE")
    assert resp.status_code == 200

    # Same cycle year (2026): A auto-supersedes with a version bump.
    plan_a_after = get_plan(plan_a["id"])
    assert plan_a_after["status"] == "SUPERSEDED"
    assert plan_a_after["version"] == version_a_approved + 1

    resp = commission_review(plan_c["id"], "APPROVE")
    assert resp.status_code == 200

    # Supersession is cycle-scoped: approving C (2027) leaves B (2026) untouched.
    plan_b_after = get_plan(plan_b["id"])
    assert plan_b_after["status"] == "APPROVED"


def test_reopen_resets_windows_and_preferred_pin(api):
    """PRD §3.8: "The transition `REJECTED → DRAFT` increments `reopen_count` by 1,
    unfreezes every portfolio (`FROZEN → DRAFT`, each portfolio's `version` bumping),
    unlocks every forecast row, clears `preferred_portfolio_id`, `approved_snapshot_id`,
    both comment-window dates, and `submitted_on`, and bumps the plan's `version` —
    returning the plan to a fully editable state for another pass through the cycle."
    PRD §2.4: "The public comment window lasts thirty calendar days from the date the
    plan opens for comment."

    Design: Corner/cross_cutting_layers/reopen_resets_windows_and_preferred_pin
    """
    plan, _portfolio = setup_plan_rejected(plan_name="IRP RW")

    reopened = validate_success(api_client.reopen_plan(plan["id"], PLANNER))
    assert reopened["comment_window_opens_on"] is None
    assert reopened["comment_window_closes_on"] is None
    assert reopened["submitted_on"] is None
    assert reopened["preferred_portfolio_id"] is None

    # A fresh open-comment re-stamps the window from the then-current clock date
    # (2026-08-31 after the review), closing thirty calendar days later.
    reopened_again = open_plan_for_comment(plan["id"])
    assert reopened_again["comment_window_opens_on"] == "2026-08-31"
    assert reopened_again["comment_window_closes_on"] == "2026-09-30"
    assert reopened_again["submitted_on"] == "2026-08-31"
    # The preferred pin is only re-established at the next submit-for-review.
    assert reopened_again["preferred_portfolio_id"] is None


def test_mutations_visible_immediately_in_same_response(api):
    """PRD §3.8: "Approval, `UNDER_REVIEW → APPROVED`, sets the plan's
    `approved_snapshot_id` to the preferred portfolio's most recent snapshot by
    `created_at` descending (ties are not broken by id; the server rejects ambiguity
    rather than guessing)."
    PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will
    return the created or updated resource object in the data field."

    Design: Corner/consistency_model/mutations_visible_immediately_in_same_response
    """
    set_clock(CLOCK_AUG_01)
    plan, portfolio = _build_under_review_plan("IRP IC", 2026)
    snapshot_id = get_success_data(
        api_client.list_snapshots(portfolio["id"], PLANNER)
    )[0]["id"]
    set_clock(CLOCK_AUG_31)
    submitted = submit_plan_for_review(plan["id"])

    resp = api.commission_review(
        plan["id"],
        {"decision": "APPROVE_WITH_CONDITIONS",
         "expected_plan_version": submitted["version"],
         "conditions": [{"description": "Annual deviation report",
                         "required_procurement_mw": 0}]},
        COMMISSIONER,
    )
    reviewed = validate_success(resp)
    assert reviewed["status"] == "APPROVED_WITH_CONDITIONS"
    assert reviewed["approved_snapshot_id"] == snapshot_id
    assert reviewed["version"] == submitted["version"] + 1

    # The response itself carries the mutation; a follow-up read agrees exactly.
    reread = get_plan(plan["id"])
    assert reread["status"] == reviewed["status"]
    assert reread["approved_snapshot_id"] == reviewed["approved_snapshot_id"]
    assert reread["version"] == reviewed["version"]
