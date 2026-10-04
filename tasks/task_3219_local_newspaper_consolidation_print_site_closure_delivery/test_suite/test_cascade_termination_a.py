"""Difficulty queue A — transitive_cascade from the delivery-network trigger.

Terminating a contractor mutates its route, that route mutation re-costs the route
at the terminated status factor, and that re-cost itself re-examines the hub's
legal-notice ratio. The chain originates from a delivery-network transition rather
than from a market transition.
"""
import pytest

from test_helpers import (
    api,
    setup_market_with_route,
    setup_contractor_with_costed_route,
    terminate_contractor_response,
    get_delivery_route,
    get_print_market,
    validate_success,
    TEST_USERS,
)
from test_helpers.constants import CLOCK_2026_09_30

DELIVERY = TEST_USERS["delivery_manager_headers"]
PRINT_OPS = TEST_USERS["print_ops_headers"]


@pytest.fixture
def costed_contractor_scenario():
    """Contractor Cedar Hill with a live costed route and a 28000-copy edition."""
    hub, site, region, market, route = setup_market_with_route(
        clock=CLOCK_2026_09_30)
    contractor, delivery_route, stops, edition = setup_contractor_with_costed_route(
        hub["id"], market["id"], site["id"], stop_count=5,
        run_date="2026-09-21", copies=28000, slug="2026-09-20",
        rescue_prepared_sibling=True)
    return hub, site, region, market, contractor, delivery_route, stops, edition


def test_termination_is_the_hop_that_moves_the_contractor(costed_contractor_scenario):
    """PRD §3.3: "Termination is terminal: it requires the contractor to be `active`
    or `suspended` and to have no route still `prepared`."

    Design: Difficulty/transitive_cascade/contractor_termination_cascade_route_to_hub_ratio
    """
    hub, site, region, market, contractor, delivery_route, stops, edition = (
        costed_contractor_scenario)

    response = terminate_contractor_response(contractor["id"])
    terminated = validate_success(response, 200)

    assert terminated["status"] == "terminated", (
        f"hop 1: expected terminated, got {terminated['status']}"
    )


def test_the_route_mutation_rescores_at_the_terminated_factor(
        costed_contractor_scenario):
    """PRD §3.3: "It terminates every route, sets `contractor_status_factor` to
    0.85 on each, rescoring `route_night_cost` and `cost_per_copy_cents`".

    Design: Difficulty/transitive_cascade/contractor_termination_cascade_route_to_hub_ratio
    """
    hub, site, region, market, contractor, delivery_route, stops, edition = (
        costed_contractor_scenario)

    assert delivery_route["route_night_cost"] == pytest.approx(6325.00, abs=0.01)
    assert delivery_route["contractor_status_factor"] == pytest.approx(1.00, abs=1e-9)

    validate_success(terminate_contractor_response(contractor["id"]), 200)
    rescored = get_delivery_route(delivery_route["id"])

    assert rescored["contractor_status_factor"] == pytest.approx(0.85, abs=1e-9), (
        f"hop 2: expected the terminated status factor, got "
        f"{rescored['contractor_status_factor']}"
    )
    # §3.3's stop term counts the stops on *this* route, floored at the contractor's
    # min_stop_guarantee of 3: 3 * 1150 * 1.10 taps the sample's copy-volume tier,
    # and the 0.85 factor then rescales it.
    assert rescored["route_night_cost"] == pytest.approx(3225.75, abs=0.01), (
        f"hop 3: the re-cost must apply the factor, got {rescored['route_night_cost']}"
    )
    assert rescored["route_night_cost"] != pytest.approx(6325.00, abs=0.01)


def test_the_recost_rederives_the_market_boycott_flag(costed_contractor_scenario):
    """PRD §3.3: "recomputes each affected market's `delivery_boycott_active` —
    which reads true once no stop in the market is still `active`, and is the
    precondition a market must satisfy to be withdrawable."

    Design: Difficulty/transitive_cascade/contractor_termination_cascade_route_to_hub_ratio
    """
    hub, site, region, market, contractor, delivery_route, stops, edition = (
        costed_contractor_scenario)

    validate_success(terminate_contractor_response(contractor["id"]), 200)
    refreshed = get_print_market(market["id"])

    assert refreshed["delivery_boycott_active"] is True, (
        "hop 4: every stop on the terminated route is terminated, so no active "
        f"stop remains: {refreshed['delivery_boycott_active']}"
    )
    assert refreshed["status"] == "active"

    for stop in stops:
        assert validate_success(
            api.get_delivery_stop(stop["id"], DELIVERY), 200)["status"] == "terminated"