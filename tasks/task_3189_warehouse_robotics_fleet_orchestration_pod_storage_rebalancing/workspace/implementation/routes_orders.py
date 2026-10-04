"""Customer orders blueprint."""

from flask import Blueprint, request

import errors
from calculations import recompute_shift_plans
from cascades import cancel_pick_task_with_release, entity_out, list_out
from db import store
from middleware import require_roles
from models import (
    base_entity,
    bump,
    fmt_iso,
    get_or_404,
    opt_int,
    parse_iso,
    req_int,
    req_str,
    require_field,
)
from response import parse_pagination, success_list, success_object

bp = Blueprint("customer_orders", __name__)

READ_ROLES = {"FleetAdmin", "FlowController", "StationOperator"}


@bp.route("/customer-orders", methods=["POST"])
def create_order():
    require_roles({"FlowController"})
    body = request.get_json(silent=True) or {}
    order_code = req_str(body, "order_code")
    cutoff_raw = req_str(body, "cutoff_at")
    cutoff_dt = parse_iso(cutoff_raw, "cutoff_at")
    priority = opt_int(body, "priority", default=0, minimum=0)
    lines = require_field(body, "lines")
    if not isinstance(lines, list) or len(lines) == 0:
        raise errors.validation("lines must be a non-empty array")
    for o in store.orders.values():
        if o["order_code"] == order_code:
            raise errors.validation(f"order_code already exists: {order_code}")
    parsed_lines = []
    for raw in lines:
        if not isinstance(raw, dict):
            raise errors.validation("each line must be an object")
        sku_id = require_field(raw, "sku_id")
        if not isinstance(sku_id, str):
            raise errors.validation("line sku_id must be a string")
        get_or_404(store.skus, sku_id, "sku")
        qty = req_int(raw, "quantity", minimum=1)
        parsed_lines.append((sku_id, qty))
    order = base_entity()
    order.update(
        {
            "order_code": order_code,
            "status": "RECEIVED",
            "cutoff_at": fmt_iso(cutoff_dt),
            "priority": priority,
            "_cutoff_dt": cutoff_dt,
        }
    )
    store.orders[order["id"]] = order
    for sku_id, qty in parsed_lines:
        line = base_entity()
        line.update(
            {
                "order_id": order["id"],
                "sku_id": sku_id,
                "quantity": qty,
                "quantity_picked": 0,
            }
        )
        store.order_lines[line["id"]] = line
    recompute_shift_plans()
    return success_object(entity_out(order), status=201)


@bp.route("/customer-orders", methods=["GET"])
def list_orders():
    require_roles(READ_ROLES)
    limit, offset = parse_pagination()
    status_f = request.args.get("status")
    items = list(store.orders.values())
    if status_f is not None:
        items = [o for o in items if o["status"] == status_f]
    items.sort(key=lambda o: o["created_at"])
    total = len(items)
    return success_list(list_out(items[offset : offset + limit]), limit, offset, total)


@bp.route("/customer-orders/<order_id>", methods=["GET"])
def get_order(order_id):
    require_roles(READ_ROLES)
    order = get_or_404(store.orders, order_id, "customer order")
    return success_object(entity_out(order))


@bp.route("/customer-orders/<order_id>/lines", methods=["GET"])
def order_lines(order_id):
    require_roles(READ_ROLES)
    get_or_404(store.orders, order_id, "customer order")
    limit, offset = parse_pagination()
    items = sorted(
        (ln for ln in store.order_lines.values() if ln["order_id"] == order_id),
        key=lambda ln: ln["created_at"],
    )
    total = len(items)
    return success_list(list_out(items[offset : offset + limit]), limit, offset, total)


@bp.route("/customer-orders/<order_id>/pick-tasks", methods=["GET"])
def order_pick_tasks(order_id):
    require_roles(READ_ROLES)
    get_or_404(store.orders, order_id, "customer order")
    limit, offset = parse_pagination()
    items = sorted(
        (t for t in store.pick_tasks.values() if t["order_id"] == order_id),
        key=lambda t: t["created_at"],
    )
    total = len(items)
    return success_list(list_out(items[offset : offset + limit]), limit, offset, total)


@bp.route("/customer-orders/<order_id>/cancel", methods=["POST"])
def cancel_order(order_id):
    require_roles({"FlowController"})
    order = get_or_404(store.orders, order_id, "customer order")
    if order["status"] not in {"RECEIVED", "PLANNED"}:
        raise errors.invalid_state("order is not RECEIVED or PLANNED")
    order_tasks = [t for t in store.pick_tasks.values() if t["order_id"] == order_id]
    for t in order_tasks:
        if t["status"] in {"PICKING", "DISPATCHED", "DELIVERED"}:
            raise errors.invalid_state(
                "order has a task in PICKING, DISPATCHED, or DELIVERED"
            )
    for t in order_tasks:
        if t["status"] in {"CREATED", "QUEUED"}:
            cancel_pick_task_with_release(t)
    order["status"] = "CANCELLED"
    bump(order)
    recompute_shift_plans()
    return success_object(entity_out(order))
