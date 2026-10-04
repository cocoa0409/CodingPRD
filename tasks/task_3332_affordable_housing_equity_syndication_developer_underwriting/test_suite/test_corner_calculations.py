"""Breadth: computed values with a pinned evaluation order."""

import pytest

from test_helpers import (
    TEST_USERS,
    add_guarantee,
    add_project,
    api_client,
    exercise_exit_action,
    form_fund,
    get_success_data,
    issue_call,
    onboard_developer,
    plan_exit_event,
    read_project,
    schedule_capital_call,
    set_logical_clock,
    settle_call,
    setup_project_in_compliance_period,
)

_CLOCK_FIFTH_CALL = "2027-06-15T00:00:00Z"
_CLOCK_EXIT = "2043-06-01T00:00:00Z"


def _exit_pricing_scenario():
    """A compliance-period project with four PAID calls and one DEFICIENT call.

    Each of the four gating calls is issued at the 0.20 band, so each settles at
    round(105887208 * 1.20) = 127064650 and the cumulative distributions are
    508258600. A fifth call settles 1000 cents short and is DEFICIENT, which is
    the single shortfall surcharge applied to the option price.
    """
    scenario = setup_project_in_compliance_period()
    project_id = scenario.project["id"]

    fifth = schedule_capital_call(
        project_id,
        "PLACED_IN_SERVICE",
        scheduled_date="2027-06-10T00:00:00Z",
        due_date="2027-07-10T00:00:00Z",
    )
    set_logical_clock(_CLOCK_FIFTH_CALL)
    fifth = issue_call(fifth["id"])
    fifth = settle_call(
        fifth["id"],
        fifth["called_amount_cents"] - 1000,
        scenario.investor["id"],
    )
    assert fifth["status"] == "DEFICIENT"

    set_logical_clock(_CLOCK_EXIT)
    assert read_project(project_id)["status"] == "EXIT_ELIGIBLE"
    scenario.fifth = fifth
    return scenario


def test_cumulative_distributions_sum_only_the_paid_calls():
    """PRD §3.9: "the `cumulative_distributions_cents`, which is the sum of
    `settled_amount_cents` across the project's `PAID` capital calls, is subtracted
    from that stepped-up figure".

    Four calls settle at 127064650 each; the fifth is DEFICIENT and is excluded.

    Design: Corner/calculations/exit_option_price_pinned_evaluation_order_beats_reassociation
    """
    scenario = _exit_pricing_scenario()
    exit_event = plan_exit_event(scenario.project["id"])

    issued = exercise_exit_action(exit_event["id"], "ISSUE_NOTICE")

    assert issued["cumulative_distributions_cents"] == 508258600
    assert issued["status"] == "OPTION_NOTICE_ISSUED"


def test_option_price_applies_the_three_pinned_rounding_steps_in_order():
    """PRD §3.9: "First, the project's `underwritten_equity_cents` is multiplied
    by 1.05 and rounded half-up to a whole cent, producing a five percent equity
    step-up. Second, the `cumulative_distributions_cents`, which is the sum of
    `settled_amount_cents` across the project's `PAID` capital calls, is subtracted from that stepped-up figure, and the difference is rounded half-up. Third, the
    result is multiplied by one plus 0.01 for each capital call of the project
    that is `DEFICIENT` or `ADJUSTED`, and that product is rounded half-up.
    PRD §3.9: "The three roundings are sequential and the order is pinned; a
    different order yields a different cent total."

    round(529436038 * 1.05) = 555907840; 555907840 - 508258600 = 47649240;
    round(47649240 * 1.01) = 48125732.

    Design: Corner/calculations/exit_option_price_pinned_evaluation_order_beats_reassociation
    """
    scenario = _exit_pricing_scenario()
    exit_event = plan_exit_event(scenario.project["id"])

    issued = exercise_exit_action(exit_event["id"], "ISSUE_NOTICE")

    assert issued["option_price_cents"] == 48125732


def test_operating_deficit_and_dscr_are_derived_from_the_project_inputs():
    """PRD §3.4: "The `operating_deficit_cents` is the `debt_service_cents` minus
    the `operating_pro_forma_noi_cents`, floored at zero."
    PRD §3.4: "The `dscr` is the `operating_pro_forma_noi_cents` divided by the
    `debt_service_cents`, held to 4 decimal places."

    A 60000000-cent NOI against 72000000 of debt service is a 12000000 deficit
    and a DSCR of 60000000 / 72000000 = 0.8333.

    Design: Corner/calculations/operating_deficit_coverage_uses_floor_division_on_liquid_assets
    """
    developer = onboard_developer()
    fund = form_fund()
    project = add_project(
        developer["id"],
        fund["id"],
        project_name="Riverside Commons",
        operating_pro_forma_noi_cents=60000000,
        debt_service_cents=72000000,
    )

    assert project["operating_deficit_cents"] == 12000000
    assert project["dscr"] == pytest.approx(0.8333, abs=1e-6)


def test_an_operating_deficit_draw_is_refused_when_the_sponsor_covers_a_year():
    """PRD §3.6: "the monthly deficit is the `operating_deficit_cents` divided by
    12 and rounded half-up to a whole cent, the annual deficit is the
    `operating_deficit_cents` taken as it stands but never below zero, and the
    coverage months are the developer's `liquid_assets_cents` divided by the
    monthly deficit using integer floor division, with the divisor never below
    one. The developer is considered covered when those months reach at least 12,
    and an operating deficit draw is permitted only when the developer is not
    covered."

    Liquid assets of 30000000 against a 1000000 monthly deficit give exactly 30
    months, so the draw is refused and the guarantee is left untouched.

    Design: Corner/calculations/operating_deficit_coverage_uses_floor_division_on_liquid_assets
    """
    developer = onboard_developer()
    fund = form_fund()
    project = add_project(
        developer["id"],
        fund["id"],
        project_name="Riverside Commons",
        operating_pro_forma_noi_cents=60000000,
        debt_service_cents=72000000,
    )
    guarantee = add_guarantee(
        project["id"],
        guarantee_type="OPERATING_DEFICIT",
        guaranteed_amount_cents=90000000,
        recapture_pct=0.0,
    )

    response = api_client.draw_guarantee(
        guarantee["id"], 10000000, TEST_USERS["asset_manager_headers"]
    )

    assert 400 <= response.status_code < 500, (
        "a sponsor covering 30 months of deficit is covered and the draw must fail"
    )
    from test_helpers import list_project_guarantees

    stored = list_project_guarantees(project["id"])[0]
    assert stored["drawn_amount_cents"] == 0
    assert stored["status"] == "ACTIVE"
