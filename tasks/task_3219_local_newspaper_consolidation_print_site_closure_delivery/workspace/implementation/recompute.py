"""Cross-aggregate recomputation helpers shared by several blueprints."""
from core import DB
from models import bump, touch
import calcs as C


def hub_bump(hub):
    """A hub-level invariant was re-evaluated: refresh updated_at, version += 1."""
    if hub is not None:
        bump(hub)


def recompute_region(region, hub=None, bump_row=True):
    if region is None:
        return region
    hub = hub or DB.get("region_hubs", region.get("region_hub_id"))
    region["region_need_score"] = C.region_need_score(region)
    region["member_market_count"] = len(C.markets_of_region(region["id"]))
    if hub is not None:
        C.recompute_hub_allocation(hub)
    if bump_row:
        touch(region)
    return region


def recompute_site(site):
    if site is None:
        return site
    site["capacity_copies"] = (int(site.get("press_units") or 0)
                               * int(site.get("shifts_per_night") or 0) * 8
                               * int(site.get("copies_per_hour_per_press") or 0))
    allocated = 0
    for ed in C.editions_of_site(site["id"]):
        allocated += int(ed.get("allocated_print_run_copies") or 0)
    site["allocated_copies"] = allocated
    site["capacity_remaining_copies"] = max(0, site["capacity_copies"] - allocated)
    return site


def recompute_route_transport(route):
    if route is None:
        return route
    C.compute_route_transport(route)
    touch(route)
    return route


def recompute_market_derived(market):
    if market is None:
        return market
    C.transfer_ledger(market)
    C.single_copy_decision(market)
    market["route_selection_status"] = route_selection_status(market)
    market["delivery_boycott_active"] = C.delivery_boycott_active(market)
    market["transfer_cost_disputed"] = (
        market.get("status") == "withdrawn"
        and float(market.get("net_print_site_transfer_cost_cents") or 0) != 0.0)
    return market


def route_selection_status(market):
    route = DB.get("print_routes", market.get("selected_print_route_id"))
    if route is None:
        return "needs_reassignment"
    if route.get("status") == "orphaned":
        return "needs_reassignment"
    return "current"


def recompute_region_status(region):
    markets = C.markets_of_region(region["id"])
    if markets and all(m.get("status") == "withdrawn" for m in markets):
        if region.get("status") != "consolidated":
            region["status"] = "consolidated"
            for pos in DB.all("newsroom_positions"):
                if pos.get("region_id") == region["id"]:
                    pos["status"] = "closed"
                    touch(pos)
            touch(region)
    return region


def recompute_hub_posture(hub):
    if hub is None:
        return hub
    C.recompute_press_posture(hub)
    return hub


def refresh_hub_block(hub):
    if hub is None:
        return hub
    C.refresh_legal_notice_block(hub)
    hub_bump(hub)
    return hub


def recompute_market_print_routes(market):
    """route_transport_cost feeds the transfer ledger, so refresh it first."""
    for route in DB.all("print_routes"):
        if route.get("destination_market_id") == market["id"]:
            C.compute_route_transport(route)
            touch(route)


def recompute_edition(edition):
    if edition is None:
        return edition
    market = DB.get("print_markets", edition.get("print_market_id"))
    site = DB.get("print_sites", edition.get("assigned_print_site_id"))
    route = None
    if market is not None:
        route = DB.get("print_routes", market.get("selected_print_route_id"))
    if site is None or market is None or route is None:
        return edition
    C.recompute_edition_time(edition, market, site, route)
    touch(edition)
    return edition


def recompute_site_allocations(site):
    """Re-run allocation for every edition assigned to a site, in slug order."""
    recompute_site(site)
    editions = sorted(C.editions_of_site(site["id"]),
                      key=lambda e: (str(e.get("slug") or ""),
                                     str(e.get("print_market_id") or "")))
    for ed in editions:
        market = DB.get("print_markets", ed.get("print_market_id"))
        ed["allocated_print_run_copies"] = C.allocate_copies(
            site, market, ed.get("requested_print_run_copies"), editions)
        touch(ed)
    recompute_site(site)
    return site


def recompute_delivery_route(route):
    if route is None:
        return route
    C.route_night_cost(route)
    touch(route)
    return route


def recompute_market_routes(market):
    for route in C.routes_into_market(market["id"]):
        recompute_delivery_route(route)


def recompute_contractor_routes(contractor):
    for route in C.routes_of_contractor(contractor["id"]):
        recompute_delivery_route(route)


def market_route_cost_total(market):
    return sum(float(r.get("route_night_cost") or 0)
               for r in C.routes_into_market(market["id"]))


def recompute_position(position):
    if position is None:
        return position
    total = 0
    for ch in DB.all("newsroom_changes"):
        if ch.get("newsroom_position_id") == position["id"]:
            total += int(ch.get("allocated_slots") or 0)
    position["allocated_headcount"] = total
    touch(position)
    return position