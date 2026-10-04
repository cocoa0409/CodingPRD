"""
Composite setup helpers — delivery contractors, routes, stops and the
print-volume savings feed.
"""
from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .factories import (
    create_contractor_payload,
    create_delivery_route_payload,
    create_delivery_stop_payload,
    print_volume_payload,
)
from .test_users import PRINT_OPS, DELIVERY_MANAGER, CUSTOMER_SERVICE
from .constants import CLOCK_2026_09_30


# ─── Contractors ─────────────────────────────────────────────────────

def create_contractor(hub_id, **overrides):
    """Register a delivery contractor in a hub. Returns the contractor dict."""
    return get_success_data(api_client.create_contractor(
        hub_id, create_contractor_payload(**overrides), DELIVERY_MANAGER))


def create_contractor_response(hub_id, **overrides):
    """Register a contractor and return the raw Response (for error paths)."""
    return api_client.create_contractor(
        hub_id, create_contractor_payload(**overrides), DELIVERY_MANAGER)


def get_contractor(contractor_id):
    """Read a delivery contractor."""
    return get_success_data(api_client.get_contractor(contractor_id, DELIVERY_MANAGER))


def suspend_contractor(contractor_id, reason="SANCTION"):
    """Suspend a contractor with an explicit reason code."""
    return get_success_data(api_client.suspend_contractor(
        contractor_id, {"sanction_reason_code": reason}, DELIVERY_MANAGER))


def drive_routes_out_of_prepared(contractor_id, run_date="2026-09-30"):
    """§3.3: termination requires no route still `prepared`, so cost each one.

    A route leaves `prepared` on its first cost run, which is the only lever the
    PRD gives the client for that precondition.
    """
    for route in list_contractor_routes(contractor_id):
        if route.get("status") == "prepared":
            cost_run(route["id"], run_date)
    return list_contractor_routes(contractor_id)


def terminate_contractor(contractor_id):
    """Terminate a contractor. Returns the contractor dict."""
    drive_routes_out_of_prepared(contractor_id)
    return get_success_data(api_client.terminate_contractor(contractor_id, DELIVERY_MANAGER))


def terminate_contractor_response(contractor_id):
    """Terminate a contractor and return the raw Response (for error paths)."""
    return api_client.terminate_contractor(contractor_id, DELIVERY_MANAGER)


def reinstate_contractor(contractor_id):
    """Reinstate a suspended contractor."""
    return get_success_data(api_client.reinstate_contractor(contractor_id, DELIVERY_MANAGER))


# ─── Delivery routes ─────────────────────────────────────────────────

def create_delivery_route(contractor_id, market_id, **overrides):
    """Create a delivery route under a contractor. Returns the route dict."""
    return get_success_data(api_client.create_delivery_route(
        contractor_id, create_delivery_route_payload(market_id, **overrides),
        DELIVERY_MANAGER))


def create_delivery_route_response(contractor_id, market_id, **overrides):
    """Create a delivery route and return the raw Response (for error paths)."""
    return api_client.create_delivery_route(
        contractor_id, create_delivery_route_payload(market_id, **overrides),
        DELIVERY_MANAGER)


def get_delivery_route(route_id):
    """Read a delivery route."""
    return get_success_data(api_client.get_delivery_route(route_id, DELIVERY_MANAGER))


def cost_run(route_id, run_date):
    """Advance a route's nightly cost run. Returns the route dict."""
    return get_success_data(api_client.cost_run(
        route_id, {"run_date": run_date}, DELIVERY_MANAGER))


def cost_run_response(route_id, run_date):
    """Advance a route's cost run and return the raw Response (for error paths)."""
    return api_client.cost_run(route_id, {"run_date": run_date}, DELIVERY_MANAGER)


def list_contractor_routes(contractor_id):
    """List a contractor's delivery routes."""
    return get_success_data(api_client.list_contractor_routes(contractor_id, DELIVERY_MANAGER))


def list_delivery_routes(params=None):
    """List delivery routes, optionally filtered."""
    return get_success_data(api_client.list_delivery_routes(DELIVERY_MANAGER, params))


# ─── Delivery stops ──────────────────────────────────────────────────

def create_stop(route_id, market_id, **overrides):
    """Add a delivery stop to a route. Returns the stop dict."""
    return get_success_data(api_client.create_delivery_stop(
        route_id, create_delivery_stop_payload(market_id, **overrides), DELIVERY_MANAGER))


def create_stop_response(route_id, market_id, **overrides):
    """Add a stop and return the raw Response (for error paths)."""
    return api_client.create_delivery_stop(
        route_id, create_delivery_stop_payload(market_id, **overrides), DELIVERY_MANAGER)


def create_stops(route_id, market_id, count, start_index=1, **overrides):
    """Add `count` stops S1..Snn to a route. Returns the list of stop dicts."""
    stops = []
    for i in range(start_index, start_index + count):
        stops.append(create_stop(
            route_id, market_id, stop_code=f"S{i}", **overrides))
    return stops


def get_stop(stop_id):
    """Read a delivery stop."""
    return get_success_data(api_client.get_delivery_stop(stop_id, DELIVERY_MANAGER))


def list_route_stops(route_id):
    """List a route's delivery stops."""
    return get_success_data(api_client.list_route_stops(route_id, DELIVERY_MANAGER))


def pause_stop(stop_id):
    """Pause a stop inside its declared window."""
    return get_success_data(api_client.pause_stop(stop_id, DELIVERY_MANAGER))


def pause_stop_response(stop_id):
    """Pause a stop and return the raw Response (for error paths)."""
    return api_client.pause_stop(stop_id, DELIVERY_MANAGER)


def resume_stop(stop_id):
    """Resume a paused stop after its window has closed."""
    return get_success_data(api_client.resume_stop(stop_id, DELIVERY_MANAGER))


def resume_stop_response(stop_id):
    """Resume a stop and return the raw Response (for error paths)."""
    return api_client.resume_stop(stop_id, DELIVERY_MANAGER)


def terminate_stop(stop_id):
    """Terminate a stop. Returns the stop dict."""
    return get_success_data(api_client.terminate_stop(stop_id, DELIVERY_MANAGER))


def terminate_stop_response(stop_id):
    """Terminate a stop and return the raw Response (for error paths)."""
    return api_client.terminate_stop(stop_id, DELIVERY_MANAGER)


# ─── Print-volume savings feed ───────────────────────────────────────

def record_print_volume(site_id, day, charge_cents, headers=None):
    """Record one contract-day of press-volume charge for a site."""
    return get_success_data(api_client.record_print_volume(
        print_volume_payload(site_id, day, charge_cents), headers or PRINT_OPS))


def record_print_volume_response(site_id, day, charge_cents, headers=None):
    """Record one contract-day and return the raw Response (for status checks)."""
    return api_client.record_print_volume(
        print_volume_payload(site_id, day, charge_cents), headers or PRINT_OPS)


def record_days(site_id, days, charge_cents):
    """Record a list of ISO day strings at the same charge. Returns the count."""
    for day in days:
        record_print_volume(site_id, day, charge_cents)
    return len(days)


def setup_savings_window(site_id, observed_days, charge_cents=10000,
                         zero_days=0, start_day=1):
    """Seed a site's 30-day savings window.

    Records `observed_days` days at `charge_cents` starting at 2026-09-<start_day>,
    then `zero_days` days at zero charge, so observed_days counts both.
    Returns the site's freshly-read dict.
    """
    day = start_day
    for _ in range(observed_days):
        record_print_volume(site_id, f"2026-09-{day:02d}", charge_cents)
        day += 1
    for _ in range(zero_days):
        record_print_volume(site_id, f"2026-09-{day:02d}", 0)
        day += 1
    return get_success_data(api_client.get_print_site(site_id, PRINT_OPS))


# ─── Composite: contractor network under a market ────────────────────

def setup_contractor_with_route_and_stops(hub_id, market_id, stop_count=5,
                                          stop_overrides=None,
                                          route_overrides=None,
                                          contractor_overrides=None):
    """Contractor + delivery route + N stops in one market.

    Returns (contractor, delivery_route, stops).
    """
    contractor = create_contractor(hub_id, **(contractor_overrides or {}))
    delivery_route = create_delivery_route(
        contractor["id"], market_id, **(route_overrides or {}))
    stops = create_stops(delivery_route["id"], market_id, stop_count,
                         **(stop_overrides or {}))
    return contractor, delivery_route, stops


def _second_market(market_id):
    from .fixtures_market import create_market, get_market
    market = get_market(market_id)
    return create_market(market["region_id"],
                         name="Rescue %s" % market["name"],
                         weighted_demand_units=6000,
                         guaranteed_floor_copies=0,
                         publication_deadline_utc="05:30",
                         on_time_margin_minutes=30,
                         single_copy_market_rule="carrier")


def setup_contractor_with_costed_route(hub_id, market_id, site_id, stop_count=5,
                                       run_date="2026-09-21", copies=28000,
                                       slug="2026-09-20",
                                       rescue_prepared_sibling=False):
    """Contractor + route + stops + one costed edition in the market.

    Reaching a live route_night_cost requires an edition in the route's market
    and one successful cost run. Returns (contractor, delivery_route, stops,
    edition).
    """
    from .fixtures_market import create_edition
    from .constants import SITE_CED
    from .fixtures import create_site

    contractor, delivery_route, stops = setup_contractor_with_route_and_stops(
        hub_id, market_id, stop_count=stop_count)
    # §3.3: termination requires no route still `prepared`, and a prepared sibling
    # refuses the whole request. A rescue route on a second site and a second market
    # is driven live so the cascade can fire.
    if rescue_prepared_sibling:
        rescue_market = _second_market(market_id)
        rescue_site = create_site(hub_id, **SITE_CED)
        rescue_route = create_delivery_route(contractor["id"], rescue_market["id"],
                                             route_code="R-EXTRA")
        create_edition(rescue_market["id"], rescue_site["id"], slug="2026-09-19",
                       requested_print_run_copies=1000)
        cost_run(rescue_route["id"], run_date)
    edition = create_edition(market_id, site_id, slug=slug,
                             requested_print_run_copies=copies)
    delivery_route = cost_run(delivery_route["id"], run_date)
    return contractor, delivery_route, stops, edition


def setup_contractor_with_two_routes(hub_id, market_id, other_market_id):
    """Contractor with route R1 (market A, costed) and R2 (market B, prepared).

    Returns (contractor, route_r1, route_r2).
    """
    from .fixtures_market import create_edition
    contractor = create_contractor(hub_id)
    route_r1 = create_delivery_route(contractor["id"], market_id, route_code="R1")
    route_r2 = create_delivery_route(contractor["id"], other_market_id, route_code="R2")
    return contractor, route_r1, route_r2