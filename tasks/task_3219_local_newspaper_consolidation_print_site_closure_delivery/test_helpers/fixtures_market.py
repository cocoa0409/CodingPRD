"""
Composite setup helpers — print markets, print routes and the transfer cycle.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_print_market_payload,
    create_print_route_payload,
    plan_transfer_payload,
    create_edition_payload,
)
from .test_users import PRINT_OPS, DELIVERY_MANAGER, CUSTOMER_SERVICE
from .fixtures import (
    setup_hub_site_region,
    setup_hub_with_two_sites,
    create_site,
    create_region,
    hub_version,
    get_hub,
)
from .constants import CLOCK_2026_09_30


# ─── Print markets ───────────────────────────────────────────────────

def create_market(region_id, **overrides):
    """Create a print market inside a region. Returns the market dict."""
    return get_success_data(api_client.create_print_market(
        region_id, create_print_market_payload(**overrides), PRINT_OPS))


def market_full(region_id, **overrides):
    """Create a market carrying the pinned deadline/margin/floor/rule defaults."""
    defaults = {
        "publication_deadline_utc": "05:30",
        "on_time_margin_minutes": 30,
        "guaranteed_floor_copies": 8000,
        "single_copy_market_rule": "carrier",
    }
    defaults.update(overrides)
    return create_market(region_id, **defaults)


def get_market(market_id):
    """Read a print market. Returns the market dict."""
    return get_success_data(api_client.get_print_market(market_id, PRINT_OPS))


def list_region_markets(region_id, params=None):
    """List a region's print markets."""
    return get_success_data(api_client.list_region_markets(region_id, PRINT_OPS, params))


def list_markets(params=None):
    """List print markets, optionally filtered."""
    return get_success_data(api_client.list_print_markets(PRINT_OPS, params))


# ─── Print routes ────────────────────────────────────────────────────

def create_route(site_id, destination_market_id, **overrides):
    """Create a print route out of a site into a market. Returns the route dict."""
    return get_success_data(api_client.create_print_route(
        site_id, create_print_route_payload(destination_market_id, **overrides), PRINT_OPS))


def get_route(route_id):
    """Read a print route."""
    return get_success_data(api_client.get_print_route(route_id, PRINT_OPS))


def list_site_routes(site_id):
    """List a site's print routes."""
    return get_success_data(api_client.list_site_routes(site_id, PRINT_OPS))


# ─── The pinned hub + site + region + market + route chain ───────────

def setup_market_with_route(market_overrides=None, route_overrides=None,
                            clock=CLOCK_2026_09_30, site_overrides=None,
                            region_overrides=None, hub_overrides=None):
    """Clock + hub + site KOT + region North + market Riverton + route KOT->Riverton.

    Returns (hub, site, region, market, route). This is the common prefix of most
    fixture chains in this suite.
    """
    hub, site, region = setup_hub_site_region(
        site_overrides=site_overrides,
        region_overrides=region_overrides,
        clock=clock,
        hub_overrides=hub_overrides,
    )
    market = market_full(region["id"], **(market_overrides or {}))
    route = create_route(site["id"], market["id"], **(route_overrides or {}))
    return hub, site, region, market, route


def setup_market_with_two_sites(market_overrides=None, clock=CLOCK_2026_09_30):
    """Clock + hub + sites KOT/CED + region North + market + route KOT->market.

    Returns (hub, site_kot, site_ced, region, market, route_kot).
    """
    hub, site_kot, site_ced = setup_hub_with_two_sites(clock=clock)
    region = create_region(hub["id"])
    market = market_full(region["id"], **(market_overrides or {}))
    route_kot = create_route(site_kot["id"], market["id"])
    return hub, site_kot, site_ced, region, market, route_kot


def setup_markets_in_region(hub_id, region_id, count, name_prefix="M",
                            demand_units=6000, start_index=1, **overrides):
    """Create `count` markets in a region, named M01..Mnn.

    Returns the list of created market dicts in creation order.
    """
    markets = []
    for i in range(start_index, start_index + count):
        markets.append(create_market(
            region_id,
            name=f"{name_prefix}{i:02d}",
            weighted_demand_units=demand_units,
            publication_deadline_utc="05:30",
            on_time_margin_minutes=30,
            guaranteed_floor_copies=0,
            single_copy_market_rule="carrier",
            **overrides,
        ))
    return markets


# ─── Editions ────────────────────────────────────────────────────────

def create_edition(market_id, site_id, **overrides):
    """Create an edition against a market. Returns the edition dict."""
    return get_success_data(api_client.create_edition(
        market_id, create_edition_payload(site_id, **overrides), PRINT_OPS))


# ─── Transfer cycle ──────────────────────────────────────────────────

def plan_transfer(market_id, receiving_site_id, expected_version=None,
                  hub_id=None):
    """Plan a market transfer, defaulting expected_hub_version to the live hub version."""
    if expected_version is None:
        expected_version = hub_version(hub_id)
    return get_success_data(api_client.plan_market_transfer(
        market_id, plan_transfer_payload(receiving_site_id, expected_version), PRINT_OPS))


def plan_transfer_response(market_id, receiving_site_id, expected_version=None,
                           hub_id=None):
    """Plan a market transfer and return the raw Response (for error-path tests)."""
    if expected_version is None:
        expected_version = hub_version(hub_id)
    return api_client.plan_market_transfer(
        market_id, plan_transfer_payload(receiving_site_id, expected_version), PRINT_OPS)


def redispatch_market(market_id, receiving_site_id):
    """Re-point a market at a replacement route."""
    return get_success_data(api_client.redispatch_market(
        market_id, {"receiving_print_site_id": receiving_site_id}, PRINT_OPS))


def withdraw_market(market_id):
    """Withdraw a market from print distribution."""
    return get_success_data(api_client.withdraw_market(market_id, PRINT_OPS))


def setup_market_planned_on_site(clock=CLOCK_2026_09_30, market_overrides=None,
                                 route_overrides=None):
    """Full chain through a successful plan-transfer onto KOT.

    Returns (hub, site, region, market, route).
    """
    hub, site, region, market, route = setup_market_with_route(
        market_overrides=market_overrides,
        route_overrides=route_overrides,
        clock=clock,
    )
    plan_transfer(market["id"], site["id"], hub_id=hub["id"])
    return hub, site, region, market, route


def setup_market_with_edition(site_id, market_id, edition_overrides=None,
                              route_overrides=None, region_id=None, hub_id=None,
                              plan_first=True):
    """Market with an edition (and optionally a committed route).

    Requires an existing hub/site/region/market; plan_first selects the route
    before creating the edition so the edition's ready time is computed.
    Returns the edition dict.
    """
    if plan_first and hub_id is not None:
        plan_transfer(market_id, site_id, hub_id=hub_id)
    return create_edition(market_id, site_id, **(edition_overrides or {}))


def setup_edition_dispatched(clock=CLOCK_2026_09_30, page_count=8,
                             requested_copies=40000, late_sports=False,
                             legal_notice_count=0, slug="2026-09-21",
                             market_overrides=None, route_overrides=None,
                             dispatch=True, deliver=False):
    """Chain through to a created (optionally dispatched/delivered) edition.

    Returns (hub, site, region, market, route, edition).
    """
    hub, site, region, market, route = setup_market_with_route(
        market_overrides=market_overrides,
        route_overrides=route_overrides,
        clock=clock,
    )
    plan_transfer(market["id"], site["id"], hub_id=hub["id"])
    edition = create_edition(
        market["id"], site["id"],
        slug=slug,
        page_count=page_count,
        requested_print_run_copies=requested_copies,
        late_sports_engineering_flag=late_sports,
        legal_notice_count=legal_notice_count,
    )
    if dispatch:
        edition = get_success_data(api_client.dispatch_edition(edition["id"], PRINT_OPS))
    if deliver:
        edition = get_success_data(api_client.deliver_edition(edition["id"], PRINT_OPS))
    return hub, site, region, market, route, edition


def setup_market_with_cascade_chain(stop_overrides=None, subscriber_overrides=None,
                                    market_overrides=None, route_overrides=None,
                                    clock=CLOCK_2026_09_30):
    """Market + contractor route + one stop + one subscriber on that stop.

    Returns (hub, site, region, market, route, contractor, delivery_route, stop,
    subscriber). The chain most cascade tests start from.
    """
    from .fixtures_delivery import create_contractor, create_delivery_route, create_stop
    from .fixtures_subscriber import create_subscriber

    hub, site, region, market, route = setup_market_with_route(
        market_overrides=market_overrides,
        route_overrides=route_overrides,
        clock=clock,
    )
    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"])
    stop = create_stop(delivery_route["id"], market["id"], **(stop_overrides or {}))
    subscriber = create_subscriber(stop["id"], **(subscriber_overrides or {}))
    return hub, site, region, market, route, contractor, delivery_route, stop, subscriber


def plan_and_withdraw_market(hub_id, market_id, site_id, contractor_id):
    """Plan a transfer, terminate the contractor (seeding the boycott) and withdraw.

    Returns (market_after_withdrawal, hub_after_withdrawal).
    """
    plan_transfer(market_id, site_id, hub_id=hub_id)
    get_success_data(api_client.terminate_contractor(contractor_id, DELIVERY_MANAGER))
    market = withdraw_market(market_id)
    return market, get_hub(hub_id)