"""DeliveryBatch routes: plan, load, deliver, cancel."""

from flask import Blueprint, request

import db
import services.calculations as calc
import services.domain as domain
from errors import (
    ERR_BATCH_INVALID_STATE,
    ERR_COOLER_CAPACITY_EXCEEDED,
    ERR_DELIVERY_FREQUENCY_VIOLATION,
    ERR_ROUTE_INVALID_STATE,
    ERR_RUN_NOT_COMPLETED,
    conflict,
    invalid_request,
    unprocessable,
)
from middleware import require_roles
from response import success_list, success_object
from util import (
    base_entity,
    check_occ,
    get_json_body,
    paginate,
    parse_datetime,
    req_field,
    req_int,
    req_string,
    touch,
)

bp = Blueprint("batches", __name__)


@bp.route("/batches", methods=["POST"])
def create_batch():
    require_roles("CommissaryPlanner")
    body = get_json_body()
    # Shape (tier 6).
    store_id = req_string(body, "store_id")
    delivery_date = parse_datetime(req_field(body, "delivery_date"), "delivery_date")
    patty_count = req_int(body, "patty_count")
    bun_count = req_int(body, "bun_count")
    produce_units = req_int(body, "produce_units")
    # Body FK existence (tier 5).
    store = domain.get_store(store_id)
    # OCC (tier 7) — mandatory on batch planning.
    check_occ(body, store, "expected_store_version", "Store")
    b = base_entity()
    b.update({
        "store_id": store["id"],
        "commissary_id": store["commissary_id"],
        "production_run_id": None,
        "route_id": None,
        "delivery_date": delivery_date,
        "patty_count": patty_count,
        "bun_count": bun_count,
        "produce_units": produce_units,
        "cooler_cases_required": calc.cooler_cases_required(patty_count, bun_count, produce_units),
        "gap_hours_at_load": None,
        "delivered_at": None,
        "status": "PLANNED",
    })
    db.batches[b["id"]] = b
    # Planning mutates the store.
    touch(store)
    return success_object(domain.ser_batch(b), 201)


@bp.route("/stores/<sid>/batches", methods=["GET"])
def list_store_batches(sid):
    require_roles("CommissaryPlanner", "StoreManager", "SupplyChainDirector")
    store = domain.get_store(sid)
    items = [b for b in db.batches.values() if b["store_id"] == store["id"]]
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_batch(b) for b in page], limit, offset, total)


@bp.route("/batches/<bid>", methods=["GET"])
def get_batch(bid):
    require_roles("CommissaryPlanner", "StoreManager", "SupplyChainDirector")
    return success_object(domain.ser_batch(domain.get_batch(bid)))


@bp.route("/batches", methods=["GET"])
def list_batches():
    require_roles("CommissaryPlanner", "SupplyChainDirector")
    items = list(db.batches.values())
    cid = request.args.get("commissary_id")
    if cid is not None:
        items = [b for b in items if b["commissary_id"] == cid]
    rid = request.args.get("production_run_id")
    if rid is not None:
        items = [b for b in items if b.get("production_run_id") == rid]
    rt = request.args.get("route_id")
    if rt is not None:
        items = [b for b in items if b.get("route_id") == rt]
    status = request.args.get("status")
    if status is not None:
        items = [b for b in items if b["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([domain.ser_batch(b) for b in page], limit, offset, total)


@bp.route("/batches/<bid>/load", methods=["POST"])
def load_batch(bid):
    require_roles("CommissaryPlanner")
    batch = domain.get_batch(bid)
    body = get_json_body()
    production_run_id = req_string(body, "production_run_id")
    route_id = req_string(body, "route_id")
    # Body FK existence (tier 5).
    run = domain.get_production_run(production_run_id)
    route = domain.get_route(route_id)
    # State (tier 8): batch must be PLANNED.
    if batch["status"] != "PLANNED":
        raise conflict(ERR_BATCH_INVALID_STATE, "Batch must be PLANNED to load")
    # Run linkage: COMPLETED and same commissary.
    if run["status"] != "COMPLETED" or run["commissary_id"] != batch["commissary_id"]:
        raise unprocessable(ERR_RUN_NOT_COMPLETED, "Production run is not COMPLETED for this commissary")
    # Route linkage (tier 12): DRAFT/FINALIZED, same commissary, same service date,
    # store on the stop list.
    if (
        route["status"] not in ("DRAFT", "FINALIZED")
        or route["commissary_id"] != batch["commissary_id"]
        or route["service_date"].date() != batch["delivery_date"].date()
        or batch["store_id"] not in route["store_ids"]
    ):
        raise conflict(ERR_ROUTE_INVALID_STATE, "Route linkage invalid for this batch")
    # Gap check (tier 14): first batch exempt; otherwise <= effective max gap.
    store = domain.get_store(batch["store_id"])
    prev = calc.previous_delivered_batch(store["id"], batch["delivery_date"])
    gap = None
    if prev is not None:
        gap = calc.gap_hours(prev["delivered_at"], batch["delivery_date"])
        if gap > calc.effective_max_gap_hours(store):
            raise unprocessable(ERR_DELIVERY_FREQUENCY_VIOLATION, "Delivery gap exceeds effective maximum")
    # Aggregate truck cooler check (tier 18).
    truck = domain.get_truck(route["truck_id"])
    loaded_cases = sum(
        b["cooler_cases_required"] for b in db.batches.values()
        if b.get("route_id") == route["id"] and b["status"] == "LOADED"
    )
    if loaded_cases + batch["cooler_cases_required"] > truck["cooler_capacity_cases"]:
        raise unprocessable(ERR_COOLER_CAPACITY_EXCEEDED, "Cooler capacity exceeded on this route")
    batch["production_run_id"] = run["id"]
    batch["route_id"] = route["id"]
    batch["gap_hours_at_load"] = gap
    batch["status"] = "LOADED"
    touch(batch)
    return success_object(domain.ser_batch(batch))


@bp.route("/batches/<bid>/deliver", methods=["POST"])
def deliver_batch(bid):
    require_roles("CommissaryPlanner")
    batch = domain.get_batch(bid)
    # State (tier 8).
    if batch["status"] != "LOADED":
        raise conflict(ERR_BATCH_INVALID_STATE, "Batch must be LOADED to deliver")
    # Route must be FINALIZED.
    route = db.routes.get(batch.get("route_id"))
    if route is None or route["status"] != "FINALIZED":
        raise conflict(ERR_ROUTE_INVALID_STATE, "Route must be FINALIZED to deliver")
    batch["delivered_at"] = db.clock_now()
    batch["status"] = "DELIVERED"
    # Credit the store on-hand ledger.
    inv = db.inventory_for(batch["store_id"])
    inv["patties"] += batch["patty_count"]
    inv["buns"] += batch["bun_count"]
    inv["produce_units"] += batch["produce_units"]
    touch(batch)
    return success_object(domain.ser_batch(batch))


@bp.route("/batches/<bid>/cancel", methods=["POST"])
def cancel_batch(bid):
    require_roles("CommissaryPlanner")
    batch = domain.get_batch(bid)
    if batch["status"] != "PLANNED":
        raise conflict(ERR_BATCH_INVALID_STATE, "Batch must be PLANNED to cancel")
    batch["status"] = "CANCELLED"
    touch(batch)
    return success_object(domain.ser_batch(batch))
