"""Depth: the inclusive side of a threshold.

Both instances here sit a value exactly on a boundary and then move it one unit
across, so the test observes the threshold itself rather than the region around
it.
"""

import pytest

from test_helpers import (
    SCENARIO,
    add_guarantee,
    add_project,
    form_fund,
    onboard_investor,
    open_subscription,
    read_developer,
    read_fund,
    setup_canonical_scenario,
)

_RIVERSTONE = dict(SCENARIO["developer_riverstone"])
_UPTOWN = dict(SCENARIO["project_uptown"])


def _riverstone_with_project():
    """Riverstone (net worth 2000000000, not deeply experienced) and one project."""
    return setup_canonical_scenario(
        developer_overrides=_RIVERSTONE,
        with_subscription=False,
        with_project=True,
        project_overrides=_UPTOWN,
    )


def test_coverage_ratio_of_exactly_two_point_zero_is_still_eligible():
    """PRD §3.1: "A developer passes on coverage when the coverage ratio is at
    least 2.0, or when it is deeply experienced."
    PRD §3.1: "Because the coverage test uses "at least 2.0", a developer whose
    exposure sits exactly at twice its net worth is still `ELIGIBLE` unless some
    other condition fails."

    Net worth 2000000000 against 1000000000 of exposure is exactly 2.0.

    Design: Difficulty/boundary_precision_check/sponsor_coverage_ratio_exactly_two_point_zero_still_eligible
    """
    scenario = _riverstone_with_project()

    guarantee = add_guarantee(
        scenario.project["id"],
        guarantee_type="OPERATING_DEFICIT",
        guaranteed_amount_cents=1000000000,
        recapture_pct=0.0,
    )
    developer = read_developer(scenario.developer["id"])

    assert guarantee["remaining_capacity_cents"] == 1000000000
    assert developer["guarantee_exposure_cents"] == 1000000000
    assert developer["status"] == "ELIGIBLE"


def test_one_cent_more_of_exposure_drops_the_developer_to_watch():
    """PRD §3.1: "The coverage ratio is the developer's `net_worth_cents` divided
    by that exposure, except that the exposure used in the division is never
    allowed below one cent."
    PRD §3.1: "A developer is `WATCH` when it fails the coverage test, or has at
    least one distressed project, or has at least one escalated review."

    Design: Difficulty/boundary_precision_check/sponsor_coverage_ratio_exactly_two_point_zero_still_eligible
    """
    scenario = _riverstone_with_project()
    add_guarantee(
        scenario.project["id"],
        guarantee_type="OPERATING_DEFICIT",
        guaranteed_amount_cents=1000000000,
        recapture_pct=0.0,
    )
    assert read_developer(scenario.developer["id"])["status"] == "ELIGIBLE"

    add_guarantee(
        scenario.project["id"],
        guarantee_type="COMPLETION",
        guaranteed_amount_cents=1,
        recapture_pct=0.0,
        coverage_start_date="2026-10-01T00:00:00Z",
        coverage_end_date="2031-10-01T00:00:00Z",
    )
    developer = read_developer(scenario.developer["id"])

    assert developer["guarantee_exposure_cents"] == 1000000001
    assert developer["status"] == "WATCH", (
        "a coverage ratio just below 2.0 fails the coverage test"
    )


def test_subscribed_equity_exactly_at_the_close_threshold_moves_the_fund_to_closing():
    """PRD §3.3: "A fund moves from `FORMING` to `CLOSING` as soon as its
    `subscribed_equity_cents` reaches the close threshold, which is the fund's
    `target_equity_cents` multiplied by its `close_threshold_pct` and rounded
    half-up to a whole cent."

    0.85 * 500000000 is exactly 425000000.

    Design: Difficulty/boundary_precision_check/fund_close_threshold_exact_boundary_decides_closing_versus_forming
    """
    scenario = setup_canonical_scenario(
        with_subscription=False, with_project=False
    )
    subscription = open_subscription(
        scenario.fund, scenario.investor, committed_cents=425000000
    )
    fund = read_fund(scenario.fund["id"])

    assert subscription["committed_cents"] == 425000000
    assert fund["subscribed_equity_cents"] == 425000000
    assert fund["status"] == "CLOSING"


def test_one_cent_below_the_close_threshold_leaves_the_fund_forming():
    """PRD §3.3: "A fund moves from `FORMING` to `CLOSING` as soon as its
    `subscribed_equity_cents` reaches the close threshold, which is the fund's
    `target_equity_cents` multiplied by its `close_threshold_pct` and rounded
    half-up to a whole cent."

    Design: Difficulty/boundary_precision_check/fund_close_threshold_exact_boundary_decides_closing_versus_forming
    """
    scenario = setup_canonical_scenario(
        with_subscription=False, with_project=False
    )
    under_investor = onboard_investor(
        name="Northline Mutual",
        investor_type="INSURANCE",
        committed_capacity_cents=500000000,
        risk_tier="TIER_3",
    )
    second_fund = form_fund(
        fund_name="ECP Housing Fund IX",
        target_equity_cents=500000000,
        price_per_credit_dollar=0.9100,
        target_yield_pct=0.068,
        close_threshold_pct=0.85,
    )
    open_subscription(second_fund, under_investor, committed_cents=424999999)
    fund = read_fund(second_fund["id"])

    assert fund["subscribed_equity_cents"] == 424999999
    assert fund["status"] == "FORMING"
