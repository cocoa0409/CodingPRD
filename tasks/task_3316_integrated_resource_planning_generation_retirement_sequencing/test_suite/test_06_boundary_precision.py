"""Boundary precision: capacity margin zero and the comment window edges (PRD §3.5, §3.10)."""
import pytest

from test_helpers import (
    ApiErrorId,
    add_forecast,
    add_portfolio,
    compute_snapshot,
    create_comment_payload,
    create_draft_plan_with_basics,
    create_plan,
    open_plan_for_comment,
    register_resource,
    set_clock,
    submit_plan_for_review,
    validate_error,
    validate_success,
)
from test_helpers.constants import CLOCK_AUG_01, CLOCK_AUG_31
from test_helpers.fixtures import PLANNER, COMMENTER


def _setup_zero_margin_portfolio():
    """DRAFT plan with BASE forecasts for 2030 (load 400) and 2031 (load 400.01), a
    preferred portfolio, and an 1150 MW SOLAR unit accrediting exactly 460.00 MW."""
    plan = create_plan(plan_name="IRP Zero", cycle_year=2026, planning_horizon_years=15)
    add_forecast(plan["id"], scenario_tag="BASE", forecast_year=2030, residential_mw=400)
    add_forecast(plan["id"], scenario_tag="BASE", forecast_year=2031,
                 residential_mw=400.01)
    portfolio = add_portfolio(plan["id"], portfolio_name="PF-Z", preferred_flag=True)
    register_resource(unit_name="SOL-ZERO", resource_type="SOLAR", nameplate_mw=1150,
                      in_service_year=2020, fuel_type="SUN")
    return plan, portfolio


def test_capacity_margin_exactly_zero_passes(api):
    """PRD §3.5: "A snapshot `meets_requirement` when its capacity margin is zero or
    greater; a margin of exactly 0.00 passes."

    Design: Difficulty/boundary_precision_check/capacity_margin_exact_zero_passes
    """
    plan, portfolio = _setup_zero_margin_portfolio()

    snapshot = compute_snapshot(portfolio["id"], forecast_year=2030, scenario_tag="BASE")
    # 460.00 accredited minus 400.00 * 1.15 == exactly 0.00, and zero passes.
    assert snapshot["accredited_supply_mw"] == pytest.approx(460.00, abs=0.005)
    assert snapshot["capacity_margin_mw"] == pytest.approx(0.00, abs=0.005)
    assert snapshot["meets_requirement"] is True


def test_capacity_margin_one_cent_below_zero_fails(api):
    """PRD §3.5: "A snapshot `meets_requirement` when its capacity margin is zero or
    greater; a margin of exactly 0.00 passes."

    Design: Difficulty/boundary_precision_check/capacity_margin_exact_zero_passes
    """
    plan, portfolio = _setup_zero_margin_portfolio()

    snapshot = compute_snapshot(portfolio["id"], forecast_year=2031, scenario_tag="BASE")
    # 460.00 - 400.01 * 1.15 == -0.0115 -> -0.01 at 2 decimal places: just under zero.
    assert snapshot["capacity_margin_mw"] == pytest.approx(-0.01, abs=0.005)
    assert snapshot["meets_requirement"] is False


def _setup_two_open_plans():
    """Two plans OPEN_FOR_COMMENT in the window [2026-08-01, 2026-08-31]."""
    set_clock(CLOCK_AUG_01)
    plan1, _pf1 = create_draft_plan_with_basics(plan_name="IRP W1")
    open_plan_for_comment(plan1["id"])
    plan2, _pf2 = create_draft_plan_with_basics(plan_name="IRP W2")
    open_plan_for_comment(plan2["id"])
    return plan1, plan2


def test_comment_on_closing_date_accepted_and_late_rejected(api):
    """PRD §3.10: "the clock's calendar date must fall within the comment window
    inclusive of both ends — a comment filed on the closing date itself is accepted,
    while one filed before the window opens or after it closes is rejected with
    `ERR_COMMENT_WINDOW_CLOSED` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/comment_window_closes_on_inclusive
    """
    plan1, plan2 = _setup_two_open_plans()

    # On the closing date itself the comment is accepted.
    set_clock(CLOCK_AUG_31)
    resp = api.create_comment(
        plan1["id"],
        create_comment_payload(commenter_name="On Time", commenter_email="on@example.org",
                               body="Filed on the closing date."),
        COMMENTER,
    )
    comment = validate_success(resp, expected_status=201)
    assert comment["status"] == "RECEIVED"

    # One day later the same plan rejects a comment.
    set_clock("2026-09-01T00:00:00Z")
    resp = api.create_comment(
        plan2["id"],
        create_comment_payload(commenter_name="Too Late",
                               commenter_email="late@example.org",
                               body="Filed one day after close."),
        COMMENTER,
    )
    validate_error(resp, ApiErrorId.ERR_COMMENT_WINDOW_CLOSED)


def test_submit_for_review_on_closing_date_succeeds(api):
    """PRD §3.8: "Submission requires the clock's calendar date to have reached
    `comment_window_closes_on`; an early submission is rejected with
    `ERR_COMMENT_WINDOW_OPEN` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/comment_window_closes_on_inclusive
    """
    plan1, plan2 = _setup_two_open_plans()

    # Submit exactly on the closing date: "reached" is inclusive.
    set_clock(CLOCK_AUG_31)
    submitted = submit_plan_for_review(plan1["id"])
    assert submitted["status"] == "UNDER_REVIEW"

    # A day before the close, submission is still early for the second plan.
    set_clock("2026-08-30T00:00:00Z")
    resp = api.submit_for_review(plan2["id"], PLANNER)
    validate_error(resp, ApiErrorId.ERR_COMMENT_WINDOW_OPEN)
