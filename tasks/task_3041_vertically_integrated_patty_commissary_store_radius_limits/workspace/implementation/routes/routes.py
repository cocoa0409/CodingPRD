"""DeliveryRoute routes."""

from flask import Blueprint, request

import db
import services.calculations as calc
import services.domain as domain
from errors import (
    ERR_BATCHES_NOT_DELIVERED,
    ERR_COOLER_CAPACITY_EXCEEDED,
    ERR_DELIVERY_FREQUENCY_VIOLATION,
    ERR_ROUTE_INVALID_STATE,
    ERR_ROUTE_WINDOW_CONFLICT,
    ERR_TRUCK_INACTIVE,
    conflict,
    invalid_request,
    unprocessable,
)
from middleware import require_roles
from response import success_list, success_object
from util import (
    base_entity,
    get_json_body,
    paginate,
    parse_datetime,
    req_field,
    req_list,
    req_string,
    touch,
)

bp = Blueprint("routes", __name__)


def _check_truck_dispatchable(truck, store_ids):
    """Tier 23: truck must be ACTIVE; RESERVE trucks only while a served store is
    in OPENING_SURGE."""
    if truck["status"] != "ACTIVE":
        raise unprocessable(ERR_TRUCK_INACTIVE, "Truck is INACTIVE")
    if truck["route_type"] == "RESERVE" and not domain.any_store_surging_in(store_ids):
        raise unprocessable(ERR_TRUCK_INACTIVE, "RESERVE truck requires a surging store on the route")


def _check_window_conflicts(route, truck, store_ids):
    """Tier 16: truck not committed to another FINALIZED route on the same
    service_date; no store already visited by another FINALIZED route that day."""
    for r in db.routes.values():
        if r["id"] == route["id"] or r["status"] != "FINALIZED":
            continue
        if r["service_date"] != route["service_date"]:
            continue
        if r["truck_id"] == truck["id"]:
            raise unprocessable(ERR_ROUTE_WINDOW_CONFLICT, "Truck already committed on this service_date")
        if set(r["store_ids"]) & set(store_ids):
            raise unprocessable(ERR_ROUTE_WINDOW_CONFLICT, "A store is already visited by another FINALIZED route that day")


def _check_store_delivery_windows(route, store_ids):
    """Per-store delivery-day window: weekday permitted by the commissary mask and
    gap versus the store's previous DELIVERED batch within the effective max."""
    commissary = domain.get_commissary(route["commissary_id"])
    mask = commissary["delivery_days_mask"]
    wd = route["service_date"].date().weekday()
    for sid in store_ids:
        store = db.stores.get(sid)
        if store is None:
            continue
        if not mask[wd]:
            raise unprocessable(
                "ERR_DELIVERY_WINDOW_CONFLICT",
                "Service date weekday is not delivery-capable for the commissary",
            )
        prev = calc.previous_delivered_batch(store["id"], route["service_date"])
        if prev is not None:
            gap = calc.gap_hours(prev["delivered_at"], route["service_date"])
            if gap > calc.effective_max_gap_hours(store):
                raise unprocessable(
                    "ERR_DELIVERY_WINDOW_CONFLICT",
                    "Delivery gap exceeds the store's effective maximum",
                )


@bp.route("/routes", methods=["POST"])
def create_route():
    require_roles("CommissaryPlanner")
    body = get_json_body()
    # Shape (tier 6).
    commissary_id = req_string(body, "commissary_id")
    truck_id = req_string(body, "truck_id")
    service_date = parse_datetime(req_field(body, "service_date"), "service_date")
    store_ids = req_list(body, "store_ids")
    for sid in store_ids:
        if not isinstance(sid, str):
            raise invalid_request("store_ids must be an array of strings")
    # Body FK existence (tier 5).
    commissary = domain.get_commissary(commissary_id)
    truck = domain.get_truck(truck_id)
    for sid in store_ids:
        domain.get_store(sid)
    # Truck dispatchability (tier 23).
    _check_truck_dispatchable(truck, store_ids)
    r = base_entity()
    r.update({
        "commissary_id": commissary["id"],
        "truck_id": truck["id"],
        "service_date": service_date,
        "store_ids": list(store_ids),
        "status": "DRAFT",
    })
    db.routes[r["id"]] = r
    return success_object(domain.ser_route(r), 201)


@bp.route("/commissaries/<cid>/routes", methods=["GET"])
def list_commissary_routes(cid):
    require_roles("CommissaryPlanner", "SupplyChainDirector")
    c = domain.get_commissary(cid)
    items = [r for r in db.routes.values() if r["commissary_id"] == c["id"]]
    sd = request.args.get("service_date")
    if sd is not None:
        items = [r for r in items if r["service_date"].isoformat().startswith(sd[:10])]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_route(r) for r in page], limit, offset, total)


@bp.route("/routes/<rid>", methods=["GET"])
def get_route(rid):
    require_roles("CommissaryPlanner", "SupplyChainDirector")
    return success_object(domain.ser_route(domain.get_route(rid)))


@bp.route("/routes", methods=["GET"])
def list_routes():
    require_roles("CommissaryPlanner", "SupplyChainDirector")
    items = list(db.routes.values())
    tid = request.args.get("truck_id")
    if tid is not None:
        items = [r for r in items if r["truck_id"] == tid]
    cid = request.args.get("commissary_id")
    if cid is not None:
        items = [r for r in items if r["commissary_id"] == cid]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_route(r) for r in page], limit, offset, total)


@bp.route("/routes/<rid>/finalize", methods=["POST"])
def finalize_route(rid):
    require_roles("CommissaryPlanner")
    route = domain.get_route(rid)
    if route["status"] != "DRAFT":
        raise conflict(ERR_ROUTE_INVALID_STATE, "Route must be DRAFT to finalize")
    truck = domain.get_truck(route["truck_id"])
    _check_truck_dispatchable(truck, route["store_ids"])
    # Aggregate cooler check (tier 18): sum of LOADED batch cases must not exceed
    # the truck's cooler capacity.
    loaded_cases = sum(
        b["cooler_cases_required"] for b in db.batches.values()
        if b.get("route_id") == route["id"] and b["status"] == "LOADED"
    )
    if loaded_cases > truck["cooler_capacity_cases"]:
        raise unprocessable(ERR_COOLER_CAPACITY_EXCEEDED, "Loaded cases exceed cooler capacity")
    # Delivery-day windows per store (tier 14).
    _check_store_delivery_windows(route, route["store_ids"])
    # Temporal exclusivity (tier 16).
    _check_window_conflicts(route, truck, route["store_ids"])
    route["status"] = "FINALIZED"
    touch(route)
    return success_object(domain.ser_route(route))


@bp.route("/routes/<rid>/complete", methods=["POST"])
def complete_route(rid):
    require_roles("CommissaryPlanner")
    route = domain.get_route(rid)
    if route["status"] != "FINALIZED":
        raise conflict(ERR_ROUTE_INVALID_STATE, "Route must be FINALIZED to complete")
    not_delivered = any(
        b.get("route_id") == route["id"] and b["status"] != "DELIVERED"
        for b in db.batches.values()
    )
    if not_delivered:
        raise conflict(ERR_BATCHES_NOT_DELIVERED, "All batches on the route must be DELIVERED")
    route["status"] = "COMPLETED"
    touch(route)
    return success_object(domain.ser_route(route))


@bp.route("/routes/<rid>/cancel", methods=["POST"])
def cancel_route(rid):
    require_roles("CommissaryPlanner")
    route = domain.get_route(rid)
    if route["status"] not in ("DRAFT", "FINALIZED"):
        raise conflict(ERR_ROUTE_INVALID_STATE, "Route must be DRAFT or FINALIZED to cancel")
    route["status"] = "CANCELLED"
    touch(route)
    return success_object(domain.ser_route(route))
