"""Breadth: a read immediately after a write shows the write's effect."""

import pytest

from test_helpers import (
    get_success_data,
    open_subscription,
    read_fund,
    read_subscription,
    setup_canonical_scenario,
)


def _subscribed_fund():
    scenario = setup_canonical_scenario(with_subscription=False, with_project=False)
    subscription = open_subscription(
        scenario.fund, scenario.investor, committed_cents=200000000
    )
    scenario.subscription = subscription
    return scenario


def test_a_fund_read_after_a_subscription_write_shows_consistent_counters():
    """PRD §3.3: "Reading a fund recomputes and exposes
    `awarded_credits_total_cents`, `delivered_credits_total_cents`,
    `priced_value_cents`, `realized_value_cents`, `priced_yield_pct`,
    `realized_yield_pct`, and the portfolio summary counters."

    Design: Corner/consistency_model/fund_read_after_subscription_write_shows_consistent_counters_in_the_same_response
    """
    scenario = _subscribed_fund()

    fund = read_fund(scenario.fund["id"])

    assert fund["subscription_count"] == 1
    assert fund["subscribed_equity_cents"] == 200000000
    assert fund["funded_equity_cents"] == 0


def test_a_new_subscription_pins_the_fund_price_and_starts_pledged():
    """PRD §3.2: "At creation the subscription's
    `executed_price_per_credit_dollar` is pinned to the fund's current
    `price_per_credit_dollar`, and its `status` begins at `PLEDGED`."

    Design: Corner/consistency_model/fund_read_after_subscription_write_shows_consistent_counters_in_the_same_response
    """
    scenario = _subscribed_fund()

    subscription = read_subscription(scenario.subscription["id"])

    assert subscription["status"] == "PLEDGED"
    assert subscription["executed_price_per_credit_dollar"] == pytest.approx(
        0.9123, abs=1e-9
    )
    assert subscription["paid_in_cents"] == 0
    assert subscription["unfunded_commitment_cents"] == 200000000
    assert subscription["shortfall_cents"] == 0
