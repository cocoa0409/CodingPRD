"""New product launch allocation across in-service routes."""

from flask import Blueprint

import auth
import calc
import envelope
import lookup
import store
from errors import fail

bp = Blueprint("launch", __name__, url_prefix="/retail")

LAUNCH_ROLES = ("PlatformAdmin", "FranchiseOwner", "FranchiseManager", "CreditOfficer")
RUN_PRIORITIES = ("PRIMARY", "SECONDARY")
OPEN_ORDER_STATUSES = ("DRAFT", "CONFIRMED", "DELIVERED")


def open_order_count(route_id):
    return len([o for o in store.sales_orders.values()
                if o.get("route_id") == route_id
                and o.get("order_status") in OPEN_ORDER_STATUSES])


def score_for(route):
    return calc.launch_priority_score(route, open_order_count(route["id"]))


def eligible_routes():
    return [r for r in store.routes.values() if r.get("route_status") == "IN_SERVICE"]


@bp.post("/products/<product_id>/launch-allocations")
def plan_launch(product_id):
    auth.require("FranchiseManager")
    product = lookup.product(product_id)
    payload = envelope.body()
    total_launch_qty = envelope.as_int(payload, "total_launch_qty", minimum=0)
    envelope.as_enum(payload, "run_priority", RUN_PRIORITIES)
    if product.get("launch_status") in ("ALLOCATED", "LIVE"):
        fail("ERR_LAUNCH_ALREADY_ALLOCATED")

    scored = [(route, score_for(route)) for route in eligible_routes()]
    shares = calc.launch_allocation_plan(scored, total_launch_qty)
    unit_cost = product.get("unit_cost_cents", 0)

    rows = []
    for route, score in scored:
        qty = shares.get(route["id"], 0)
        band = calc.launch_risk_band(score)
        row = store.create(
            store.launch_allocations,
            product_id=product["id"],
            route_id=route["id"],
            allocation_status="ALLOCATED",
            priority_score=float(score),
            review_flag=False,
            allocated_qty=qty,
            allocated_amount_cents=qty * unit_cost,
            launch_risk_band=band,
        )
        store.set_field(route, "launch_risk_band", band)
        rows.append(row)
    store.set_field(product, "launch_status", "ALLOCATED")
    return envelope.ok_list(rows)


@bp.get("/launch-allocations")
def list_allocations():
    auth.require(*LAUNCH_ROLES)
    rows = envelope.filter_query(store.ordered(store.launch_allocations), {
        "product_id": "product_id",
        "route_id": "route_id",
        "allocation_status": "allocation_status",
        "launch_risk_band": "launch_risk_band",
    })
    page, pagination = envelope.paginate(rows)
    return envelope.ok_list(page, pagination=pagination)


@bp.post("/launch-allocations/<allocation_id>/reallocate")
def reallocate(allocation_id):
    auth.require("FranchiseManager")
    source = lookup.launch_allocation(allocation_id)
    payload = envelope.body()
    target_route_id = envelope.as_str(payload, "target_route_id")
    qty = envelope.as_int(payload, "allocated_qty", minimum=1)
    target_route = lookup.route(target_route_id)
    if target_route.get("route_status") != "IN_SERVICE":
        fail("ERR_INVALID_STATE", "The target route is not IN_SERVICE.")
    if qty > source.get("allocated_qty", 0):
        fail("ERR_INVALID_REQUEST", "allocated_qty exceeds the source allocation.")
    product = lookup.product(source.get("product_id"))

    source["allocated_qty"] = source.get("allocated_qty", 0) - qty
    source["allocated_amount_cents"] = source["allocated_qty"] * product.get("unit_cost_cents", 0)
    _refresh(source, store.routes.get(source.get("route_id")))
    store.stamp(source)

    target = None
    for row in store.launch_allocations.values():
        if (row.get("product_id") == product["id"]
                and row.get("route_id") == target_route["id"]
                and row["id"] != source["id"]):
            target = row
            break
    if target is None:
        target = store.create(
            store.launch_allocations,
            product_id=product["id"],
            route_id=target_route["id"],
            allocation_status="ALLOCATED",
            priority_score=float(score_for(target_route)),
            review_flag=False,
            allocated_qty=0,
            allocated_amount_cents=0,
            launch_risk_band=calc.launch_risk_band(score_for(target_route)),
        )
    target["allocated_qty"] = target.get("allocated_qty", 0) + qty
    target["allocated_amount_cents"] = target["allocated_qty"] * product.get("unit_cost_cents", 0)
    _refresh(target, target_route)
    store.stamp(target)
    return envelope.ok(target)


def _refresh(row, route):
    if route is None:
        return
    score = score_for(route)
    store.set_field(row, "priority_score", float(score))
    band = calc.launch_risk_band(score)
    store.set_field(row, "launch_risk_band", band)
    store.set_field(route, "launch_risk_band", band)


@bp.post("/launch-allocations/<allocation_id>/review")
def review_allocation(allocation_id):
    auth.require("FranchiseManager")
    row = lookup.launch_allocation(allocation_id)
    payload = envelope.body()
    flag = envelope.as_bool(payload, "review_flag")
    store.set_field(row, "review_flag", flag)
    store.stamp(row)
    return envelope.ok(row)
