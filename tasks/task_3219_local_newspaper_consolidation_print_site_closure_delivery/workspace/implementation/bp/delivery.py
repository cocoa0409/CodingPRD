"""Delivery contractors, delivery routes and delivery stops."""
from flask import Blueprint, request

from core import DB, fail
from helpers import ok_list, ok_object, create, sort_by_created
from guards import body, identity, path_one, require_row
from models import touch
import calcs as C
import recompute as R
import logical_time as T

bp = Blueprint("delivery", __name__)

READ_CONTRACTOR = ["DeliveryNetworkManager", "Auditor", "PlatformAdmin"]
READ_ROUTE = ["DeliveryNetworkManager", "Auditor", "PlatformAdmin"]
READ_STOP = ["DeliveryNetworkManager", "CustomerService", "Auditor", "PlatformAdmin"]


# --------------------------------------------------------------------------
# DeliveryContractor
# --------------------------------------------------------------------------
@bp.post("/regional-news-ops/region-hubs/<hub_id>/delivery-contractors")
def create_contractor(hub_id):
    data = body()
    identity(["DeliveryNetworkManager"])
    hub = path_one("region_hubs", hub_id)
    contractor = create("delivery_contractors", data,
                        ["name", "pay_basis", "per_copy_rate_cents", "min_stop_guarantee",
                         "net_60_available", "cost_per_copy_ceiling_cents",
                         "last_load_claim_weight_lbs"],
                        system={"contractor_hub_id": hub["id"]})
    if int(contractor.get("min_stop_guarantee") or 0) < 1:
        DB.col("delivery_contractors").pop(contractor["id"], None)
        fail("ERR_INVALID_REQUEST", "min_stop_guarantee must be at least 1.")
    if DB.duplicate("delivery_contractors", contractor["id"],
                 contractor_hub_id=hub["id"], name=contractor["name"]):
        DB.col("delivery_contractors").pop(contractor["id"], None)
        fail("ERR_DUPLICATE_HUB_CODE")
    contractor["status"] = "active"
    return ok_object(contractor, 201)


@bp.get("/regional-news-ops/region-hubs/<hub_id>/delivery-contractors")
def list_contractors(hub_id):
    identity(READ_CONTRACTOR)
    hub = path_one("region_hubs", hub_id)
    return ok_list(sort_by_created(C.contractors_of_hub(hub["id"])), None, None)


@bp.get("/regional-news-ops/delivery-contractors/<contractor_id>")
def get_contractor(contractor_id):
    identity(READ_CONTRACTOR)
    return ok_object(path_one("delivery_contractors", contractor_id))


@bp.post("/regional-news-ops/delivery-contractors/<contractor_id>/suspend")
def suspend_contractor(contractor_id):
    data = body()
    identity(["DeliveryNetworkManager"])
    contractor = path_one("delivery_contractors", contractor_id)
    if contractor.get("status") != "active":
        fail("ERR_INVALID_STATE")
    reason = data.get("sanction_reason_code")
    if reason is None:
        fail("ERR_INVALID_REQUEST", "sanction_reason_code is required.")
    contractor["sanction_reason_code"] = reason
    contractor["status"] = "suspended"
    touch(contractor)
    for route in C.routes_of_contractor(contractor["id"]):
        if route.get("status") == "contract_active":
            route["status"] = "suspended"
        R.recompute_delivery_route(route)
        for stop in C.stops_of_route(route["id"]):
            if stop.get("status") == "active":
                stop["status"] = "paused"
                touch(stop)
    hub = DB.get("region_hubs", contractor.get("contractor_hub_id"))
    if hub is not None:
        for market in C.markets_of_hub(hub["id"]):
            R.recompute_market_derived(market)
    return ok_object(contractor)


@bp.post("/regional-news-ops/delivery-contractors/<contractor_id>/terminate")
def terminate_contractor(contractor_id):
    data = body()
    identity(["DeliveryNetworkManager"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    contractor = path_one("delivery_contractors", contractor_id)
    if contractor.get("status") == "terminated":
        fail("ERR_CONTRACTOR_TERMINAL")
    if contractor.get("status") not in ("active", "suspended"):
        fail("ERR_INVALID_STATE")
    for route in C.routes_of_contractor(contractor["id"]):
        if route.get("status") == "prepared":
            fail("ERR_INVALID_STATE", "A route of this contractor is still prepared.")
    contractor["status"] = "terminated"
    touch(contractor)
    for route in C.routes_of_contractor(contractor["id"]):
        route["status"] = "terminated"
        touch(route)
        for stop in C.stops_of_route(route["id"]):
            if stop.get("status") in ("active", "paused"):
                stop["status"] = "terminated"
                touch(stop)
            for sub in C.subscribers_of_stop(stop["id"]):
                _churn_pending(sub)
    for route in C.routes_of_contractor(contractor["id"]):
        R.recompute_delivery_route(route)
    hub = DB.get("region_hubs", contractor.get("contractor_hub_id"))
    if hub is not None:
        for market in C.markets_of_hub(hub["id"]):
            R.recompute_market_derived(market)
            touch(market)
        C.refresh_legal_notice_block(hub)
        from models import bump
        bump(hub)
    return ok_object(contractor)


def _churn_pending(sub):
    sub["status"] = "churned_pending_retention"
    sub["offer_status"] = "offered"
    sub["delivery_status"] = "terminated"
    sub["churn_retention_credit_cents"] = C.churn_retention_credit(sub)
    touch(sub)
    return sub


@bp.post("/regional-news-ops/delivery-contractors/<contractor_id>/reinstate")
def reinstate_contractor(contractor_id):
    data = body()
    identity(["DeliveryNetworkManager"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    contractor = path_one("delivery_contractors", contractor_id)
    hub = DB.get("region_hubs", contractor.get("contractor_hub_id"))
    if contractor.get("status") == "terminated":
        fail("ERR_CONTRACTOR_TERMINAL")
    if contractor.get("status") != "suspended":
        fail("ERR_INVALID_STATE")
    if hub is not None and hub.get("press_posture") == "SUSPENDED":
        fail("ERR_PRESS_POSTURE_LOCKED")
    routes = C.routes_of_contractor(contractor["id"])
    if any(r.get("status") == "terminated" for r in routes):
        fail("ERR_BACKED_OUT_REFERENCE")
    if contractor.get("net_60_available") is not True:
        fail("ERR_INVALID_STATE")
    for route in routes:
        if float(route.get("cost_per_copy_cents") or 0) > float(
                route.get("cost_per_copy_ceiling_cents") or 0):
            fail("ERR_INVALID_STATE")
    contractor["status"] = "active"
    touch(contractor)
    for route in routes:
        if route.get("status") == "suspended":
            route["status"] = "contract_active"
        R.recompute_delivery_route(route)
        for stop in C.stops_of_route(route["id"]):
            if stop.get("status") == "paused":
                stop["status"] = "active"
                touch(stop)
    return ok_object(contractor)


# --------------------------------------------------------------------------
# DeliveryRoute
# --------------------------------------------------------------------------
@bp.post("/regional-news-ops/delivery-contractors/<contractor_id>/routes")
def create_delivery_route(contractor_id):
    data = body()
    identity(["DeliveryNetworkManager"])
    contractor = path_one("delivery_contractors", contractor_id)
    if contractor.get("status") == "terminated":
        fail("ERR_CONTRACTOR_TERMINAL")
    route = create("delivery_routes", data,
                   ["print_market_id", "route_code", "stop_capacity", "per_stop_fee_cents",
                    "dist_per_stop_miles", "cost_per_copy_ceiling_cents",
                    "printed_copies_surcharge_cents", "cost_run_date"],
                   system={"delivery_contractor_id": contractor["id"]})
    market = require_row("print_markets", route.get("print_market_id"))
    if int(route.get("stop_capacity") or 0) < 1:
        DB.col("delivery_routes").pop(route["id"], None)
        fail("ERR_INVALID_REQUEST", "stop_capacity must be at least 1.")
    if DB.duplicate("delivery_routes", route["id"],
                 delivery_contractor_id=contractor["id"],
                 route_code=route["route_code"]):
        DB.col("delivery_routes").pop(route["id"], None)
        fail("ERR_DUPLICATE_HUB_CODE")
    route["status"] = "prepared"
    route["last_cost_run_date"] = None
    route["printed_copies_last_run"] = 0
    C.route_night_cost(route)
    return ok_object(route, 201)


@bp.get("/regional-news-ops/delivery-contractors/<contractor_id>/routes")
def list_contractor_routes(contractor_id):
    identity(READ_ROUTE)
    contractor = path_one("delivery_contractors", contractor_id)
    return ok_list(sort_by_created(C.routes_of_contractor(contractor["id"])), None, None)


@bp.get("/regional-news-ops/delivery-routes/<route_id>")
def get_delivery_route(route_id):
    identity(READ_ROUTE)
    return ok_object(path_one("delivery_routes", route_id))


@bp.get("/regional-news-ops/delivery-routes")
def list_delivery_routes():
    identity(READ_ROUTE)
    rows = DB.all("delivery_routes")
    market_id = request.args.get("print_market_id")
    contractor_id = request.args.get("delivery_contractor_id")
    if market_id:
        rows = [r for r in rows if r.get("print_market_id") == market_id]
    if contractor_id:
        rows = [r for r in rows if r.get("delivery_contractor_id") == contractor_id]
    return ok_list(sort_by_created(rows), request.args.get("limit"),
                   request.args.get("offset"))


@bp.post("/regional-news-ops/delivery-routes/<route_id>/cost-run")
def cost_run(route_id):
    data = body()
    identity(["DeliveryNetworkManager"])
    route = path_one("delivery_routes", route_id)
    if "run_date" not in data or data["run_date"] is None:
        fail("ERR_INVALID_REQUEST", "run_date is required.")
    for key in data:
        if key != "run_date":
            fail("ERR_INVALID_REQUEST", "Unknown field %s." % key)
    run_date = str(data["run_date"])
    contractor = DB.get("delivery_contractors", route.get("delivery_contractor_id"))
    market = DB.get("print_markets", route.get("print_market_id"))
    if contractor.get("status") == "terminated":
        fail("ERR_CONTRACTOR_TERMINAL")
    last = route.get("last_cost_run_date")
    if last is not None and run_date <= str(last):
        fail("ERR_COST_RUN_REGRESSION")
    if route.get("status") == "prepared":
        if contractor.get("status") != "active":
            fail("ERR_INVALID_STATE")
        if len([s for s in C.stops_of_route(route["id"])
                if s.get("status") != "terminated"]) > int(route.get("stop_capacity") or 0):
            fail("ERR_INVALID_STATE")
        route["status"] = "contract_active"
    route["last_cost_run_date"] = run_date
    route["cost_run_date"] = run_date
    edition = C.latest_edition(market["id"])
    route["printed_copies_last_run"] = int(
        edition.get("allocated_print_run_copies") or 0) if edition else 0
    R.recompute_delivery_route(route)
    return ok_object(route)


# --------------------------------------------------------------------------
# DeliveryStop
# --------------------------------------------------------------------------
@bp.post("/regional-news-ops/delivery-routes/<route_id>/stops")
def create_stop(route_id):
    data = body()
    identity(["DeliveryNetworkManager"])
    route = path_one("delivery_routes", route_id)
    start = data.get("pause_start_date")
    end = data.get("pause_end_date")
    if (start is None) != (end is None):
        fail("ERR_OVERLAP_PAUSE_WINDOW")
    if start is not None and end is not None:
        ds = T.date_from_iso(start)
        de = T.date_from_iso(end)
        if ds is None or de is None or de < ds:
            fail("ERR_OVERLAP_PAUSE_WINDOW")
    market = require_row("print_markets", data.get("print_market_id"))
    active_count = len([s for s in C.stops_of_route(route["id"])
                        if s.get("status") != "terminated"])
    if active_count + 1 > int(route.get("stop_capacity") or 0):
        fail("ERR_STOP_CAPACITY_EXCEEDED")
    stop = create("delivery_stops", data,
                  ["print_market_id", "stop_code", "contracted_daily_copies",
                   "contracted_daily_fee_cents"],
                  system={"delivery_route_id": route["id"]})
    if DB.duplicate("delivery_stops", stop["id"],
                 delivery_route_id=route["id"], stop_code=stop["stop_code"]):
        DB.col("delivery_stops").pop(stop["id"], None)
        fail("ERR_DUPLICATE_HUB_CODE")
    if start is not None and end is not None:
        stop["pause_window_days"] = (T.date_from_iso(end) - T.date_from_iso(start)).days + 1
    else:
        stop["pause_window_days"] = 0
    stop["status"] = "active"
    if market.get("status") in ("active", "consolidation_planned",
                                "transfer_in_progress"):
        if route.get("status") == "contract_active":
            pass
    R.recompute_delivery_route(route)
    return ok_object(stop, 201)


@bp.get("/regional-news-ops/delivery-routes/<route_id>/stops")
def list_route_stops(route_id):
    identity(READ_STOP)
    route = path_one("delivery_routes", route_id)
    rows = C.stops_of_route(route["id"])
    rows.sort(key=lambda s: (str(s.get("stop_code") or ""),))
    return ok_list(rows, None, None)


@bp.get("/regional-news-ops/delivery-stops/<stop_id>")
def get_stop(stop_id):
    identity(READ_STOP)
    return ok_object(path_one("delivery_stops", stop_id))


def _refresh_market_and_hub(stop):
    market = C.market_of_stop(stop)
    if market is None:
        return
    R.recompute_market_derived(market)
    touch(market)
    hub = C.hub_for_market(market)
    if hub is not None:
        C.refresh_legal_notice_block(hub)
        from models import bump
        bump(hub)


@bp.post("/regional-news-ops/delivery-stops/<stop_id>/pause")
def pause_stop(stop_id):
    data = body()
    identity(["DeliveryNetworkManager"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    stop = path_one("delivery_stops", stop_id)
    if stop.get("status") != "active":
        fail("ERR_STOP_NOT_ACTIVE")
    start = stop.get("pause_start_date")
    end = stop.get("pause_end_date")
    today = T.today()
    if start is None or end is None:
        fail("ERR_PAUSE_WINDOW_NOT_OPEN")
    if not (T.date_from_iso(start) <= today <= T.date_from_iso(end)):
        fail("ERR_PAUSE_WINDOW_NOT_OPEN")
    stop["status"] = "paused"
    touch(stop)
    for sub in C.subscribers_of_stop(stop["id"]):
        sub["status"] = "paused"
        sub["delivery_status"] = "paused"
        touch(sub)
    _refresh_market_and_hub(stop)
    return ok_object(stop)


@bp.post("/regional-news-ops/delivery-stops/<stop_id>/resume")
def resume_stop(stop_id):
    data = body()
    identity(["DeliveryNetworkManager"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    stop = path_one("delivery_stops", stop_id)
    if stop.get("status") != "paused":
        fail("ERR_INVALID_STATE")
    end = stop.get("pause_end_date")
    if end is not None and T.today() <= T.date_from_iso(end):
        fail("ERR_PAUSE_WINDOW_STILL_OPEN")
    if stop.get("delivery_route_id") is not None:
        route = DB.get("delivery_routes", stop["delivery_route_id"])
        if route is not None and route.get("status") == "terminated":
            fail("ERR_BACKED_OUT_REFERENCE")
    stop["status"] = "active"
    touch(stop)
    for sub in C.subscribers_of_stop(stop["id"]):
        if sub.get("status") == "paused":
            sub["status"] = "active"
            sub["delivery_status"] = "resumed"
            touch(sub)
    _refresh_market_and_hub(stop)
    return ok_object(stop)


@bp.post("/regional-news-ops/delivery-stops/<stop_id>/terminate")
def terminate_stop(stop_id):
    data = body()
    identity(["DeliveryNetworkManager"])
    if data:
        fail("ERR_INVALID_REQUEST", "This operation takes no body fields.")
    stop = path_one("delivery_stops", stop_id)
    if stop.get("status") not in ("active", "paused"):
        fail("ERR_INVALID_STATE")
    stop["status"] = "terminated"
    touch(stop)
    for sub in C.subscribers_of_stop(stop["id"]):
        sub["status"] = "churned_pending_retention"
        sub["offer_status"] = "offered"
        sub["delivery_status"] = "terminated"
        sub["churn_retention_credit_cents"] = C.churn_retention_credit(sub)
        touch(sub)
    _refresh_market_and_hub(stop)
    return ok_object(stop)