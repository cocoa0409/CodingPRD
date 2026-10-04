"""Difficulty queue A — transitive_cascade, depth-3 chains.

Each hop in these chains is caused by the previous hop rather than by the original
trigger: the withdrawal mutates a stop, that stop mutation mutates the contract
carried on it, and that contract mutation recomputes the hub's ratio verdict.
"""
import pytest

from test_helpers import (
    api,
    create_hub,
    create_site,
    create_region,
    create_market,
    create_route,
    create_contractor,
    create_delivery_route,
    create_stop,
    create_subscriber,
    create_edition,
    plan_transfer,
    withdraw_market,
    get_subscriber,
    setup_market_ready_to_withdraw,
    validate_success,
    TEST_USERS,
)
from test_helpers.constants import CLOCK_2026_09_30

PRINT_OPS = TEST_USERS["print_ops_headers"]
DELIVERY = TEST_USERS["delivery_manager_headers"]
CS = TEST_USERS["customer_service_headers"]


@pytest.fixture
def cascade_scenario():
    """Hub with Riverton plus three sibling markets; a stop and subscriber in Riverton.

    Every sibling market carries an on-time edition, so withdrawing Riverton removes
    it from the counted set rather than pulling the hub below its floor.
    """
    s = setup_market_ready_to_withdraw(
        clock=CLOCK_2026_09_30,
        market_overrides={"guaranteed_floor_copies": 8000},
        subscriber_overrides={
            "subscriber_ref": "SUB-CASCADE",
            "remaining_print_issues": 40,
            "paid_through_utc": "2027-06-01T00:00:00Z",
            "print_issue_value_cents": 1200,
        },
    )
    hub, region = s["hub"], s["region"]
    assert hub["legal_notice_block"] is False
    # The four siblings are planned onto the site with an on-time edition each, so
    # withdrawing Riverton only shrinks the counted set and leaves the ratio
    # compliant (§2.9 excludes withdrawn markets from both terms).
    sib_index = []
    for name, units in (("Fallow", 6000), ("Eastport", 6000), ("Westbrook", 6000)):
        sib_index.append(name)
        market = create_market(region["id"], name=name, weighted_demand_units=units,
                               publication_deadline_utc="05:30",
                               on_time_margin_minutes=30,
                               guaranteed_floor_copies=0,
                               single_copy_market_rule="carrier")
        # §3.1: planning a transfer onto a site that already carries a market's
        # in-flight transfer is refused, so each sibling gets its own site.
        sib_site = create_site(s["hub"]["id"], code="SIB%d" % len(sib_index),
                               max_concurrent_departures=2)
        create_route(sib_site["id"], market["id"])
        edition = create_edition(market["id"], sib_site["id"], slug="2026-09-21",
                                 page_count=8, requested_print_run_copies=1000)
        plan_transfer(market["id"], sib_site["id"], hub_id=hub["id"])
    return s


def test_withdrawal_terminates_the_market_stop(cascade_scenario):
    """PRD §3.2: "terminates every one of its delivery routes and every `active` or
    `paused` stop on them".
    PRD §3.2: "Withdrawing the market sets `print_site_transfer_credit_cents` to the
    exact negation of `print_site_transfer_cost_cents`, driving
    `net_print_site_transfer_cost_cents` to exactly 0.00".

    Design: Difficulty/transitive_cascade/market_withdrawal_cascade_stop_to_hub_ratio
    """
    s = cascade_scenario

    withdrawn = withdraw_market(s["market"]["id"])
    assert withdrawn["net_print_site_transfer_cost_cents"] == pytest.approx(0.0, abs=0.01)

    stop = validate_success(api.get_delivery_stop(s["stop"]["id"], DELIVERY), 200)
    assert stop["status"] == "terminated", (
        f"hop 2: the withdrawal must terminate the stop, got {stop['status']}"
    )


def test_the_stop_termination_moves_the_contract_into_retention(cascade_scenario):
    """PRD §3.2: "moves every subscriber contract on those stops into retention
    (§3.6) with `offer_status` `offered` and `delivery_status` `terminated`."
    PRD §3.6: "for contracts whose remaining contract value is at least 20,000
    cents, creates one retention offer row for the subscriber."

    Design: Difficulty/transitive_cascade/market_withdrawal_cascade_stop_to_hub_ratio
    """
    s = cascade_scenario

    withdraw_market(s["market"]["id"])
    contract = get_subscriber(s["subscriber"]["id"])

    assert contract["status"] == "churned_pending_retention", (
        f"hop 3: expected churned_pending_retention, got {contract['status']}"
    )
    assert contract["delivery_status"] == "terminated"
    assert contract["offer_status"] == "offered"
    assert contract["churn_retention_credit_cents"] == 5000


def test_the_contract_mutation_recomputes_the_hub_ratio(cascade_scenario):
    """PRD §3.2: "the hub's `legal_notice_block` is recomputed and its `version`
    increments by 1."
    PRD §2.9: "markets whose status is `withdrawn` are excluded from both the
    numerator and the denominator, because they no longer receive print."

    Design: Difficulty/transitive_cascade/market_withdrawal_cascade_stop_to_hub_ratio
    """
    s = cascade_scenario

    hub_before = validate_success(api.get_hub(s["hub"]["id"], PRINT_OPS), 200)
    withdraw_market(s["market"]["id"])
    hub_after = validate_success(api.get_hub(s["hub"]["id"], PRINT_OPS), 200)

    compliance = validate_success(
        api.get_hub_compliance(s["hub"]["id"], TEST_USERS["auditor_headers"]), 200)

    assert compliance["counted_market_count"] == 3, (
        f"the withdrawn market leaves the denominator, got "
        f"{compliance['counted_market_count']}"
    )
    assert compliance["on_time_market_count"] == 3
    assert compliance["is_legal_notice_ratio_compliant"] is True
    assert hub_after["legal_notice_block"] is False, (
        "hop 4: the ratio verdict is refreshed and stays compliant here"
    )
    assert hub_after["version"] > hub_before["version"], (
        f"the hub version must advance: {hub_before['version']} -> {hub_after['version']}"
    )