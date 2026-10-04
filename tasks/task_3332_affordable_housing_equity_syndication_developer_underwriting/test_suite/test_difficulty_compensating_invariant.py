"""Depth: quantities conserved across a forward/compensating action pair.

Each instance pairs an action with the action that undoes it and asserts the
conserved total returned to its pre-action value to the cent.
"""

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_credit_dollars_conserved,
    assert_subscribed_equity_conserved,
    commit_project,
    list_project_allocations,
    list_subscriptions_data,
    read_fund,
    read_investor,
    read_project,
    read_subscription,
    setup_defaulted_subscription,
    setup_finalized_project,
)

_AWARD = 912345678


def test_commit_raises_the_committed_credit_dollar_total_by_the_award():
    """PRD §3.4: "With a single allocation awarded a given number of cents, the
    sequence through the total must read zero, then that amount, then zero
    exactly."

    Design: Difficulty/compensating_invariant/commit_then_rescind_conserves_committed_credit_dollars
    """
    scenario = setup_finalized_project()
    project_id = scenario.project["id"]
    assert read_project(project_id)["committed_credit_dollars_cents"] == 0

    committed = commit_project(project_id)

    assert committed["committed_credit_dollars_cents"] == _AWARD
    allocation = list_project_allocations(project_id)[0]
    assert allocation["status"] == "COMMITTED"


def test_rescinding_after_the_commit_returns_the_total_to_zero():
    """PRD §3.4: "The credit-dollar invariant pairs a commitment with a rescission:
    a commitment moves every `RESERVED` or `AWARDED` allocation into `COMMITTED`,
    and a subsequent rescission of one of those allocations moves it out again, so
    the project's `committed_credit_dollars_cents` after the pair equals its value
    immediately before the commitment."

    Design: Difficulty/compensating_invariant/commit_then_rescind_conserves_committed_credit_dollars
    """
    scenario = setup_finalized_project()
    project_id = scenario.project["id"]
    allocation_id = scenario.allocation["id"]

    before = read_project(project_id)["committed_credit_dollars_cents"]
    assert before == 0

    committed = commit_project(project_id)
    assert committed["committed_credit_dollars_cents"] == _AWARD

    from test_helpers import get_success_data

    rescinded = get_success_data(
        api_client.rescind_allocation(
            project_id, allocation_id, TEST_USERS["asset_manager_headers"]
        )
    )
    after = read_project(project_id)["committed_credit_dollars_cents"]

    assert rescinded["status"] == "RESCINDED"
    assert after == 0
    assert_credit_dollars_conserved(before, after)


def test_a_short_settlement_defaults_the_subscription_and_suspends_its_investor():
    """PRD §3.5: "when a subscription's accumulated `shortfall_cents` exceeds 20
    percent of its `committed_cents`, rounded half-up, the subscription becomes
    `DEFAULTED` rather than merely underfunded, and its investor becomes
    `SUSPENDED`."

    The call is issued at the 0.20 band on a fully committed allocation, so
    round(105887208 * 1.20) = 127064650 is called; a 1000000-cent settlement
    leaves 126064650 of shortfall, above the 92000000-cent band.

    Design: Difficulty/compensating_invariant/subscription_then_default_conserves_subscribed_equity
    """
    scenario = setup_defaulted_subscription()

    subscription = read_subscription(scenario.subscription["id"])
    investor = read_investor(scenario.investor["id"])

    assert subscription["shortfall_cents"] == 126064650
    assert subscription["status"] == "DEFAULTED"
    assert investor["status"] == "SUSPENDED"


def test_a_defaulted_subscription_leaves_the_subscribed_equity_total_conserved():
    """PRD §3.4: "after the pair the fund's `subscribed_equity_cents` plus the sum
    of `committed_cents` across the fund's defaulted subscriptions equals the sum
    of `committed_cents` across all of the fund's subscriptions, exactly, and the
    fund's `subscribed_equity_cents` has returned to its pre-creation value to the
    cent."

    Design: Difficulty/compensating_invariant/subscription_then_default_conserves_subscribed_equity
    """
    scenario = setup_defaulted_subscription()

    fund = read_fund(scenario.fund["id"])
    subscriptions = list_subscriptions_data()
    defaulted = [s for s in subscriptions if s["status"] == "DEFAULTED"]

    assert fund["subscribed_equity_cents"] == 0
    assert len(defaulted) == 1
    assert defaulted[0]["id"] == scenario.subscription["id"]
    assert_subscribed_equity_conserved(fund, subscriptions)
