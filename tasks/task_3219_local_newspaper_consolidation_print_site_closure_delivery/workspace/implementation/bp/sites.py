"""Print site lifecycle and print routes."""
from flask import Blueprint, request

from core import DB, fail
from helpers import ok_list, ok_object, create, sort_by_created
from guards import body, identity, path_one, query_pagination
from models import bump, touch
import calcs as C
import recompute as R
import logical_time as T

bp = Blueprint("sites", __name__)

READ_SITE = ["PrintOperationsDirector", "DeliveryNetworkManager", "Auditor", "PlatformAdmin"]
READ_ROUTE = ["PrintOperationsDirector", "Auditor", "PlatformAdmin"]


@bp.post("/regional-news-ops/region-hubs/<hub_id>/print-sites")
def create_site(hub_id):
    data = body()
    identity(["PrintOperationsDirector"])
    hub = path_one("region_hubs", hub_id)
    if hub.get("press_posture") == "SUSPENDED":
        fail("ERR_PRESS_POSTURE_LOCKED")
    site = create("print_sites", data,
                  ["code", "press_units", "shifts_per_night", "copies_per_hour_per_press",
                   "max_concurrent_departures", "allocation_method"],
                  system={"print_site_hub_id": hub["id"]})
    if site["code"] is None or str(site["code"]) == "":
        DB.col("print_sites").pop(site["id"], None)
        fail("ERR_INVALID_REQUEST", "code must not be empty.")
    for field, minimum in (("press_units", 1), ("shifts_per_night", 1),
                           ("copies_per_hour_per_press", 1),
                           ("max_concurrent_departures", 1),
                           ("distinct_shifts_per_night", 1),
                           ("loading_slot_minutes", 1)):
        if int(site.get(field) or 0) < minimum:
            DB.col("print_sites").pop(site["id"], None)
            fail("ERR_INVALID_REQUEST", "%s must be at least %d." % (field, minimum))
    if DB.duplicate("print_sites", site["id"], print_site_hub_id=hub["id"], code=site["code"]):
        DB.col("print_sites").pop(site["id"], None)
        fail("ERR_DUPLICATE_HUB_CODE")
    site["status"] = "active"
    site["allocated_copies"] = 0
    C.site_savings(site)
    R.recompute_site(site)
    return ok_object(site, 201)


@bp.get("/regional-news-ops/region-hubs/<hub_id>/print-sites")
def list_sites(hub_id):
    identity(READ_ROUTE)
    hub = path_one("region_hubs", hub_id)
    rows = [s for s in DB.all("print_sites") if s.get("print_site_hub_id") == hub["id"]]
    return ok_list(sort_by_created(rows), None, None)


@bp.get("/regional-news-ops/print-sites/<site_id>")
def get_site(site_id):
    identity(READ_SITE)
    return ok_object(path_one("print_sites", site_id))


def _transfer_ceiling_ok(market, hub):
    """Would the market's transfer cost stay inside the hub ceiling?"""
    cost = float(market.get("print_site_transfer_cost_cents") or 0)
    ceiling = float(hub.get("transfer_cost_ceiling_cents") or 0)
    return cost <= ceiling


@bp.post("/regional-news-ops/print-sites/<site_id>/plan-closure")
def plan_closure(site_id):
    data = body()
    identity(["PrintOperationsDirector"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    site = path_one("print_sites", site_id)
    if site.get("status") == "closed":
        fail("ERR_PRESS_POSTURE_LOCKED")
    hub = C.hub_for_site(site)
    if hub is None:
        fail("ERR_RESOURCE_NOT_FOUND")
    if hub.get("press_posture") == "SUSPENDED":
        fail("ERR_PRESS_POSTURE_LOCKED")
    if site.get("status") != "active":
        fail("ERR_INVALID_STATE")
    if hub.get("press_posture") not in ("OPEN", "RESTRICTED"):
        fail("ERR_INVALID_STATE")
    routes = C.routes_of_site(site["id"])
    affected = []
    for route in routes:
        market = C.market_of_route(route)
        if market is None:
            continue
        if market["id"] not in [m["id"] for m in affected]:
            affected.append(market)
    # transfer-cost-ceiling check and zero-lateness precondition
    for market in affected:
        if not _transfer_ceiling_ok(market, hub):
            fail("ERR_TRANSFER_COST_CEILING_EXCEEDED")
        for ed in C.editions_of_market(market["id"]):
            if int(ed.get("minutes_late") or 0) != 0:
                fail("ERR_INVALID_STATE",
                     "A latest edition on a market served by this site is late.")
    # side effects
    for route in routes:
        if route.get("status") in ("eligible", "committed"):
            route["status"] = "orphaned"
            touch(route)
    for market in affected:
        selected = DB.get("print_routes", market.get("selected_print_route_id"))
        orphaned_here = selected is not None and selected.get("status") == "orphaned"
        if orphaned_here:
            market["route_selection_status"] = "needs_reassignment"
        if orphaned_here and market.get("status") == "consolidation_planned":
            # system event: the receiving site entered closing
            market["status"] = "transfer_in_progress"
            for ed in C.editions_of_market(market["id"]):
                ed["assigned_print_site_id"] = site["id"]
                R.recompute_edition(ed)
            R.recompute_site(site)
        R.recompute_market_print_routes(market)
        R.recompute_market_derived(market)
        touch(market)
    site["status"] = "closing"
    C.site_savings(site)
    touch(site)
    C.recompute_press_posture(hub)
    # §2.9: every event that can change a market's on-time status re-examines the
    # ratio, and a closure re-points and recomputes every affected edition.
    C.refresh_legal_notice_block(hub)
    T_hub_bump(hub)
    return ok_object(site)


def T_hub_bump(hub):
    C.refresh_legal_notice_block(hub)
    bump(hub)


@bp.post("/regional-news-ops/print-sites/<site_id>/begin-consolidating")
def begin_consolidating(site_id):
    data = body()
    identity(["PrintOperationsDirector"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    site = path_one("print_sites", site_id)
    if site.get("status") == "closed":
        fail("ERR_PRESS_POSTURE_LOCKED")
    if site.get("status") not in ("active", "closing"):
        fail("ERR_INVALID_STATE")
    for route in C.routes_of_site(site["id"]):
        market = C.market_of_route(route)
        if market is not None and market.get("status") != "withdrawn":
            fail("ERR_INVALID_STATE", "A market served by this site is not withdrawn.")
    if int(site.get("allocated_copies") or 0) != 0:
        fail("ERR_INVALID_STATE", "The site still carries allocated copies.")
    site["status"] = "consolidating"
    C.site_savings(site)
    touch(site)
    hub = C.hub_for_site(site)
    if hub is not None:
        C.recompute_press_posture(hub)
        bump(hub)
    return ok_object(site)


@bp.post("/regional-news-ops/print-sites/<site_id>/close")
def close_site(site_id):
    data = body()
    identity(["PrintOperationsDirector"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    site = path_one("print_sites", site_id)
    if site.get("status") == "closed":
        fail("ERR_PRESS_POSTURE_LOCKED")
    hub = C.hub_for_site(site)
    if site.get("status") == "closing":
        for route in C.routes_of_site(site["id"]):
            if route.get("status") != "orphaned":
                fail("ERR_INVALID_STATE", "A print route of this site is not orphaned.")
            market = C.market_of_route(route)
            if market is not None and market.get("status") != "withdrawn":
                fail("ERR_INVALID_STATE", "A market served by this site is not withdrawn.")
    elif site.get("status") == "consolidating":
        pass
    else:
        fail("ERR_INVALID_STATE")
    site["status"] = "closed"
    C.site_savings(site)
    touch(site)
    if hub is not None:
        C.recompute_press_posture(hub)
        for region in C.regions_of_hub(hub["id"]):
            R.recompute_region_status(region)
        bump(hub)
    for region in C.regions_of_hub(hub["id"]) if hub else []:
        for pos in DB.all("newsroom_positions"):
            if pos.get("region_id") == region["id"] and region.get("status") == "consolidated":
                pos["status"] = "closed"
    return ok_object(site)


# --------------------------------------------------------------------------
# PrintRoute
# --------------------------------------------------------------------------
def _overlaps(a_start, a_minutes, b_start, b_minutes):
    a_end = a_start + __import__("datetime").timedelta(minutes=a_minutes)
    b_end = b_start + __import__("datetime").timedelta(minutes=b_minutes)
    return a_start < b_end and b_start < a_end


@bp.post("/regional-news-ops/print-sites/<site_id>/routes")
def create_route(site_id):
    data = body()
    identity(["PrintOperationsDirector"])
    site = path_one("print_sites", site_id)
    if site.get("status") == "closed":
        fail("ERR_PRESS_POSTURE_LOCKED")
    route = create("print_routes", data,
                   ["destination_market_id", "transit_minutes", "dispatch_cutoff_utc",
                    "is_direct_hop"], system={"origin_print_site_id": site["id"]})
    market = C.market_of_route(route)
    if market is None:
        DB.col("print_routes").pop(route["id"], None)
        fail("ERR_REFERENCE_NOT_FOUND")
    if int(route.get("transit_minutes") or 0) < 1:
        DB.col("print_routes").pop(route["id"], None)
        fail("ERR_INVALID_REQUEST", "transit_minutes must be at least 1.")
    start = T.cutoff_dt(route)
    slot = int(site.get("loading_slot_minutes") or 30)
    overlapping = 0
    for other in C.routes_of_site(site["id"]):
        if other["id"] == route["id"]:
            continue
        if _overlaps(start, slot, T.cutoff_dt(other),
                     int(site.get("loading_slot_minutes") or 30)):
            overlapping += 1
    if overlapping >= int(site.get("max_concurrent_departures") or 1):
        DB.col("print_routes").pop(route["id"], None)
        fail("ERR_DOCK_SLOT_CONFLICT")
    route["status"] = "eligible"
    C.compute_route_transport(route)
    return ok_object(route, 201)


@bp.get("/regional-news-ops/print-sites/<site_id>/routes")
def list_site_routes(site_id):
    identity(READ_ROUTE)
    site = path_one("print_sites", site_id)
    # §2.3: list endpoints return resources in ascending creation order unless a
    # business rule pins another ordering (the allocation selector's slug order is
    # internal and does not surface on this list).
    return ok_list(sort_by_created(C.routes_of_site(site["id"])), None, None)


@bp.get("/regional-news-ops/print-routes/<route_id>")
def get_route(route_id):
    identity(READ_SITE)
    return ok_object(path_one("print_routes", route_id))


@bp.get("/regional-news-ops/print-routes")
def list_routes():
    identity(READ_ROUTE)
    market_id = request.args.get("destination_market_id")
    rows = DB.all("print_routes")
    if market_id:
        rows = [r for r in rows if r.get("destination_market_id") == market_id]
    rows = sort_by_created(rows)
    return ok_list(rows, request.args.get("limit"), request.args.get("offset"))


@bp.get("/regional-news-ops/print-routes/<route_id>/print-markets")
def route_markets(route_id):
    identity(READ_ROUTE)
    route = path_one("print_routes", route_id)
    rows = [m for m in DB.all("print_markets")
            if m.get("selected_print_route_id") == route["id"]]
    return ok_list(sort_by_created(rows), None, None)


@bp.get("/regional-news-ops/print-sites/<site_id>/editions")
def site_editions(site_id):
    identity(READ_ROUTE)
    site = path_one("print_sites", site_id)
    rows = [e for e in C.editions_of_site(site["id"])]
    rows.sort(key=lambda e: (str(e.get("slug") or ""), str(e.get("print_market_id") or "")))
    return ok_list(rows, None, None)