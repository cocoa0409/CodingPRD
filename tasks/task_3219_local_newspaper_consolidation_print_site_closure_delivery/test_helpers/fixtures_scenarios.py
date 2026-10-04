"""
Scenario builders — multi-hop chains that several rule blocks share.

These compose the lower-tier helpers into the exact states the deeper tests
need (a withdrawable market, a suspended hub under a legal-notice hold).
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .test_users import PRINT_OPS, DELIVERY_MANAGER, CUSTOMER_SERVICE
from .fixtures import get_hub, hub_version
from .fixtures_market import (
    setup_market_with_route,
    setup_market_with_cascade_chain,
    create_market,
    create_route,
    create_edition,
    plan_transfer,
    market_full,
)
from .fixtures_delivery import (
    create_contractor,
    create_delivery_route,
    create_stop,
    terminate_contractor,
    terminate_stop,
)
from .fixtures_subscriber import create_subscriber
from .constants import CLOCK_2026_09_30


def activate_transfer_in_progress(hub_id, market_id, site_id):
    """Plan a transfer, then put the receiving site into closing.

    Planning sets the route committed; closing the site orphans it, which is the
    system event that moves the market to transfer_in_progress. Returns the
    market dict after the site closure.
    """
    plan_transfer(market_id, site_id, hub_id=hub_id)
    get_success_data(api_client.plan_site_closure(site_id, PRINT_OPS))
    return get_success_data(api_client.get_print_market(market_id, PRINT_OPS))


def setup_market_ready_to_withdraw(clock=CLOCK_2026_09_30, market_overrides=None,
                                   route_overrides=None, stop_count=1,
                                   subscriber_overrides=None):
    """Full chain to a market that satisfies every withdrawal precondition.

    Chain: hub + site KOT + region + market + route -> edition -> plan-transfer
    -> site closure (market becomes transfer_in_progress and needs reassignment)
    -> contractor + route + stops -> contractor termination (boycott active).

    Returns a dict of the named rows plus a "stop"/"subscriber" entry when the
    chain created them (single stop / subscriber only).
    """
    hub, site, region, market, route = setup_market_with_route(
        market_overrides=market_overrides,
        route_overrides=route_overrides,
        clock=clock,
    )
    edition = create_edition(market["id"], site["id"], slug="2026-09-21",
                             requested_print_run_copies=40000)
    market = activate_transfer_in_progress(hub["id"], market["id"], site["id"])

    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"])
    stops = []
    subscriber = None
    for i in range(1, stop_count + 1):
        stop = create_stop(delivery_route["id"], market["id"], stop_code=f"S{i}")
        stops.append(stop)
        if i == 1 and subscriber_overrides is not None:
            subscriber = create_subscriber(stop["id"], **subscriber_overrides)
    terminate_contractor(contractor["id"])

    return {
        "hub": hub,
        "site": site,
        "region": region,
        "market": market,
        "route": route,
        "edition": edition,
        "contractor": contractor,
        "delivery_route": delivery_route,
        "stops": stops,
        "stop": stops[0],
        "subscriber": subscriber,
    }


def setup_hub_suspended_and_blocked(clock=CLOCK_2026_09_30):
    """A hub that is simultaneously SUSPENDED and under a legal-notice hold.

    Chain: hub + site KOT + region + market Riverton + route -> plan-transfer ->
    site closure -> open a frequency reduction -> terminate the market's only
    stop (sets legal_notice_block true) -> contractor termination -> withdraw the
    market -> close the site (the hub's only site, so press_posture SUSPENDED).

    Returns a dict with hub/site/region/market/route/contractor/stop rows.
    """
    from .fixtures_market import create_edition

    hub, site, region, market, route = setup_market_with_route(clock=clock)
    plan_transfer(market["id"], site["id"], hub_id=hub["id"])
    # The edition is created after the transfer commits so it derives a ready time
    # (§3.5), which is what keeps the hub's ratio gate compliant before the notices.
    create_edition(market["id"], site["id"], slug="2026-09-21", page_count=8,
                   requested_print_run_copies=20000)

    # §3.1: closing the receiving site is what moves the market to
    # transfer_in_progress, which withdrawal is accepted from.
    get_success_data(api_client.plan_site_closure(site["id"], PRINT_OPS))

    # §3.7: the reduction is opened last, now that the hub's ratio has been restored
    # by the closure's recompute and the frequency dimension is still `none`.
    get_success_data(api_client.open_frequency_change(
        market["id"], {"target_print_edition_per_week": 3}, PRINT_OPS))

    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"])
    stop = create_stop(delivery_route["id"], market["id"], stop_code="S1")
    terminate_stop(stop["id"])

    get_success_data(api_client.withdraw_market(market["id"], PRINT_OPS))
    get_success_data(api_client.close_print_site(site["id"], PRINT_OPS))

    return {
        "hub": get_hub(hub["id"]),
        "site": get_success_data(api_client.get_print_site(site["id"], PRINT_OPS)),
        "region": region,
        "market": get_success_data(api_client.get_print_market(market["id"], PRINT_OPS)),
        "route": route,
        "contractor": contractor,
        "delivery_route": delivery_route,
        "stop": stop,
    }


def setup_ratio_at_floor_with_sites(clock=CLOCK_2026_09_30, on_time_count=9,
                                    late_count=1, site_overrides=None):
    """Hub with ten counted markets, `on_time_count` of them on time.

    Every market gets an edition; the late one carries the late-sports flag and a
    deadline that pushes it past the pinned cutoff. Returns (hub, site, region,
    markets, editions).
    """
    from .fixtures import create_hub_with_clock, create_site, create_region

    from .fixtures_market import create_route

    hub = create_hub_with_clock(clock, min_on_time_ratio_pct=90)
    # Every counted market needs a selected route for its edition to derive a
    # ready time, so the site declares enough dock room for one route per market.
    site_defaults = {"max_concurrent_departures": 12}
    site_defaults.update(site_overrides or {})
    site = create_site(hub["id"], **site_defaults)
    region = create_region(hub["id"])

    markets, editions, routes = [], [], []
    total = on_time_count + late_count
    for i in range(1, total + 1):
        market = create_market(
            region["id"],
            name=f"M{i:02d}",
            weighted_demand_units=6000,
            publication_deadline_utc="05:30",
            on_time_margin_minutes=30,
            guaranteed_floor_copies=0,
            single_copy_market_rule="carrier",
        )
        markets.append(market)
        is_late = i > on_time_count
        # The route is created before the edition and selected before the next
        # market is laid out, so each edition picks up a ready time (§3.5). Every
        # market uses the same slug, so the route is named by its market — a
        # GET /print-routes/{id} needs the id the market selected.
        # The pinned route (cutoff 01:00, transit 120, buffer 45) makes a 0.25-hour
        # run ready at 05:00 against a 05:30 deadline and a 30-minute margin, which
        # is exactly the on-time boundary; the 12-page sibling lands 15 minutes later.
        route = create_route(site["id"], market["id"])
        market = plan_transfer(market["id"], site["id"], hub_id=hub["id"])
        markets[-1] = market
        editions.append(create_edition(
            market["id"], site["id"],
            slug="2026-09-21",
            page_count=8 if not is_late else 12,
            # 1000 copies lands inside the first quarter hour for both page counts,
            # so the late market needs a run that really pushes past the deadline.
            requested_print_run_copies=1000 if not is_late else 40000,
            late_sports_engineering_flag=is_late,
        ))
        routes.append(route)
    return hub, site, region, markets, editions, routes


def setup_market_with_single_stop(clock=CLOCK_2026_09_30, market_overrides=None,
                                  route_overrides=None, stop_overrides=None,
                                  subscriber_overrides=None):
    """Market + contractor route + one stop (+optional subscriber).

    No edition and no transfer — the lightest market chain. Returns a dict.
    """
    hub, site, region, market, route = setup_market_with_route(
        market_overrides=market_overrides,
        route_overrides=route_overrides,
        clock=clock,
    )
    contractor = create_contractor(hub["id"])
    delivery_route = create_delivery_route(contractor["id"], market["id"])
    stop = create_stop(delivery_route["id"], market["id"], **(stop_overrides or {}))
    subscriber = None
    if subscriber_overrides is not None:
        subscriber = create_subscriber(stop["id"], **subscriber_overrides)
    return {
        "hub": hub,
        "site": site,
        "region": region,
        "market": market,
        "route": route,
        "contractor": contractor,
        "delivery_route": delivery_route,
        "stop": stop,
        "subscriber": subscriber,
    }