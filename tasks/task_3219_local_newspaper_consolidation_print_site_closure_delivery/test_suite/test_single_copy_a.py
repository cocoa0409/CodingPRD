"""Difficulty queue A — dual_variant_calc on the single-copy assortment domain.

The newsstand rule earns only on what actually sells and charges the route's whole
transport cost against those copies; the carrier rule counts the whole run as sold
and charges only each copy's own marginal delivery cost. The market follows
whichever rule its `single_copy_market_rule` names.
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
    create_stops,
    create_edition,
    get_print_market,
    get_print_route,
    plan_transfer,
    hub_version,
    validate_success,
    TEST_USERS,
)
from test_helpers.constants import CLOCK_2026_09_30

ADMIN = TEST_USERS["platform_admin_headers"]
PRINT_OPS = TEST_USERS["print_ops_headers"]
DELIVERY = TEST_USERS["delivery_manager_headers"]

COPIES = 40000
PER_COPY_REVENUE = 45
SELL_THROUGH = 0.65


@pytest.fixture
def market_with_five_stops():
    """Market Riverton (carrier rule) + route KOT->Riverton + 5 stops + a 40000-copy run.

    The route transport cost with five counted stops is 96.25, so the two variants
    read differently off the same run.
    """
    api.set_current_utc({"current_utc": CLOCK_2026_09_30}, ADMIN)
    hub = create_hub()
    site = create_site(hub["id"])
    region = create_region(hub["id"])
    market = create_market(region["id"], per_copy_revenue_cents=PER_COPY_REVENUE,
                           publication_deadline_utc="05:30",
                           on_time_margin_minutes=30, guaranteed_floor_copies=8000,
                           single_copy_market_rule="carrier")
    route = create_route(site["id"], market["id"])
    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"])
    stops = create_stops(delivery_route["id"], market["id"], 5)
    plan_transfer(market["id"], site["id"], hub_id=hub["id"])
    edition = create_edition(market["id"], site["id"], slug="2026-09-21",
                             page_count=12,
                             requested_print_run_copies=COPIES)
    return hub, site, region, market, route, stops, edition


def test_newsstand_rule_charges_the_whole_route_against_sold_copies(
        market_with_five_stops):
    """PRD §3.3: "Under the `newsstand` rule, only what actually sells earns: the
    copies sold is the `allocated_print_run_copies` multiplied by the sell-through
    rate of 0.65 and floored to a whole number, and
    `newsstand_contribution_cents` is those copies multiplied by the market's
    `per_copy_revenue_cents`, minus the route's whole `route_transport_cost`,
    rounded half up to two decimals."

    Design: Difficulty/dual_variant_calc/single_copy_newsstand_vs_carrier_rule
    """
    hub, site, region, market, route, stops, edition = market_with_five_stops

    route_row = get_print_route(route["id"])
    assert route_row["route_transport_cost"] == 96.25, (
        f"five counted stops must cost 90.00 + 6.25, got "
        f"{route_row['route_transport_cost']}"
    )

    refreshed = get_print_market(market["id"])
    sold = int(COPIES * SELL_THROUGH)
    expected = round(sold * PER_COPY_REVENUE - route_row["route_transport_cost"], 2)

    assert refreshed["newsstand_contribution_cents"] == pytest.approx(1169903.75, abs=0.01), (
        f"expected 1169903.75, got {refreshed['newsstand_contribution_cents']}"
    )
    assert refreshed["newsstand_contribution_cents"] == pytest.approx(expected, abs=0.01)


def test_carrier_rule_charges_only_each_copy_s_marginal_cost(market_with_five_stops):
    """PRD §3.3: "Under the `carrier` rule the whole run counts as sold and each
    copy bears only its own marginal delivery cost: `carrier_contribution_cents` is
    `allocated_print_run_copies` multiplied by `per_copy_revenue_cents`, minus
    `allocated_print_run_copies` multiplied by the route's
    `marginal_cost_per_copy_cents`, rounded half up to two decimals."

    Design: Difficulty/dual_variant_calc/single_copy_newsstand_vs_carrier_rule
    """
    hub, site, region, market, route, stops, edition = market_with_five_stops

    refreshed = get_print_market(market["id"])
    route_row = get_print_route(route["id"])
    expected = round(
        COPIES * PER_COPY_REVENUE
        - COPIES * route_row["marginal_cost_per_copy_cents"],
        2,
    )

    assert refreshed["carrier_contribution_cents"] == pytest.approx(1799904.00, abs=0.01), (
        f"expected 1799904.00, got {refreshed['carrier_contribution_cents']}"
    )
    assert refreshed["carrier_contribution_cents"] == pytest.approx(expected, abs=0.01)


def test_the_market_keeps_the_record_its_own_rule_names(market_with_five_stops):
    """PRD §3.3: "The market's `single_copy_market_rule` states which rule it
    follows, and `keeps_print_single_copy` reads true when that market's own rule
    reports a contribution at or above zero — the break-even being exactly zero
    under both rules".

    PRD §3.3: "so the two can disagree on the same market: returns make the
    newsstand rule look far worse, while a market comfortably profitable under the
    carrier rule may show a thin or negative margin under the newsstand rule."

    Design: Difficulty/dual_variant_calc/single_copy_newsstand_vs_carrier_rule
    """
    hub, site, region, market, route, stops, edition = market_with_five_stops

    refreshed = get_print_market(market["id"])

    assert refreshed["single_copy_market_rule"] == "carrier"
    assert refreshed["keeps_print_single_copy"] is True
    assert refreshed["carrier_contribution_cents"] >= 0
    assert (
        refreshed["newsstand_contribution_cents"]
        != refreshed["carrier_contribution_cents"]
    ), "the two variants must disagree on the same market"
    # The record kept is the one named by the rule, not the larger of the two.
    assert refreshed["keeps_print_single_copy"] is (
        refreshed["carrier_contribution_cents"] >= 0
    )