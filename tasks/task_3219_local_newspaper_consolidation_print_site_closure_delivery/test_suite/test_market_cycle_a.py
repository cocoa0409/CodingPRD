"""Difficulty queue A — non_linear_state_machine, the market transfer cycle.

The consolidation machine is a cycle rather than a pipeline: a redispatch returns
the market to active, so a second plan-transfer legitimately drives it back through
the same states before the cycle can terminate at withdrawn.
"""
import pytest

from test_helpers import (
    api,
    setup_market_with_two_sites,
    create_route,
    create_contractor,
    create_delivery_route,
    create_stop,
    plan_transfer,
    validate_success,
    get_print_market,
    TEST_USERS,
)
from test_helpers.constants import CLOCK_2026_09_30

PRINT_OPS = TEST_USERS["print_ops_headers"]
DELIVERY = TEST_USERS["delivery_manager_headers"]


@pytest.fixture
def cycle_scenario():
    """Planned market with a KOT route, two CED routes and a contractor stop.

    CED route A (transit 205) is the redispatch target; CED route B (transit 210)
    is left eligible so the second plan-transfer still has a candidate after A is
    committed.
    """
    hub, site_kot, site_ced, region, market, route_kot = setup_market_with_two_sites(
        market_overrides={"guaranteed_floor_copies": 8000},
        clock=CLOCK_2026_09_30)
    route_ced_a = create_route(site_ced["id"], market["id"], transit_minutes=45)
    route_ced_b = create_route(site_ced["id"], market["id"], transit_minutes=50)
    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"])
    stop = create_stop(delivery_route["id"], market["id"], stop_code="S1")
    plan_transfer(market["id"], site_kot["id"], hub_id=hub["id"])
    return {
        "hub": hub, "site_kot": site_kot, "site_ced": site_ced,
        "region": region, "market": market, "route_kot": route_kot,
        "route_ced_a": route_ced_a, "route_ced_b": route_ced_b,
        "contractor": contractor, "delivery_route": delivery_route, "stop": stop,
    }


def test_orphaning_the_selected_route_enters_transfer_in_progress(cycle_scenario):
    """PRD §3.2: "Once a market has been planned onto a site, and that receiving
    site later enters `closing`, the market moves automatically to
    `transfer_in_progress` — this is a system event, not a client request".
    PRD §2.5: "every market that had committed to one of those routes has its
    `route_selection_status` set to `needs_reassignment`".

    Design: Difficulty/non_linear_state_machine/print_market_transfer_cycle_reenters_in_progress
    """
    s = cycle_scenario

    validate_success(api.plan_site_closure(s["site_kot"]["id"], PRINT_OPS), 200)
    market = get_print_market(s["market"]["id"])

    assert market["status"] == "transfer_in_progress", (
        f"expected transfer_in_progress, got {market['status']}"
    )
    assert market["route_selection_status"] == "needs_reassignment"
    assert validate_success(
        api.get_print_site(s["site_kot"]["id"], PRINT_OPS), 200)["status"] == "closing"


def test_redispatch_returns_the_market_to_its_entry_state(cycle_scenario):
    """PRD §3.2: "the market returns to `active` with `route_selection_status` back
    at `current`, its editions are re-pointed at the replacement origin and
    returned to `in_production`".
    PRD §3.2: "The replacement route becomes `committed` and is recorded as the
    market's `replacement_route_id`".

    Design: Difficulty/non_linear_state_machine/print_market_transfer_cycle_reenters_in_progress
    """
    s = cycle_scenario

    validate_success(api.plan_site_closure(s["site_kot"]["id"], PRINT_OPS), 200)
    redispatched = validate_success(
        api.redispatch_market(
            s["market"]["id"],
            {"receiving_print_site_id": s["site_ced"]["id"]},
            PRINT_OPS),
        200,
    )

    assert redispatched["status"] == "active", (
        f"the cycle must return to its entry state, got {redispatched['status']}"
    )
    assert redispatched["route_selection_status"] == "current"
    assert redispatched["replacement_route_id"] == s["route_ced_a"]["id"]
    assert redispatched["selected_print_route_id"] == s["route_ced_a"]["id"]


def test_transfer_in_progress_is_reachable_twice_on_the_same_row(cycle_scenario):
    """PRD §3.2: "Once a market has been planned onto a site, and that receiving
    site later enters `closing`, the market moves automatically to
    `transfer_in_progress`".
    PRD §3.2: "A new market begins `active` with its `frequency_change_status`
    dimension `none`".

    Design: Difficulty/non_linear_state_machine/print_market_transfer_cycle_reenters_in_progress
    """
    s = cycle_scenario

    validate_success(api.plan_site_closure(s["site_kot"]["id"], PRINT_OPS), 200)
    assert get_print_market(s["market"]["id"])["status"] == "transfer_in_progress"

    validate_success(api.redispatch_market(
        s["market"]["id"],
        {"receiving_print_site_id": s["site_ced"]["id"]},
        PRINT_OPS), 200)

    hub_after = validate_success(api.get_hub(s["hub"]["id"], PRINT_OPS), 200)
    again = validate_success(
        api.plan_market_transfer(
            s["market"]["id"],
            {"receiving_print_site_id": s["site_ced"]["id"],
             "expected_hub_version": hub_after["version"]},
            PRINT_OPS),
        200,
    )

    assert again["status"] == "consolidation_planned", (
        f"the market must re-enter consolidation_planned, got {again['status']}"
    )
    assert validate_success(
        api.get_print_site(s["site_ced"]["id"], PRINT_OPS), 200)["status"] == "active"