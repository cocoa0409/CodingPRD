"""Material orders (PRD 3.8)."""
from flask import Blueprint, request

from db import STORES, new_record
from helpers import (
    body, require_roles, ok_obj, list_response, get_or_404, opt_str,
    raise_err, now_iso,
)
from errors import (
    E_INVALID_REQUEST, E_INVALID_STATE, E_PROJECT_NOT_FOUND,
    E_MATERIAL_ORDER_NOT_FOUND, E_INSUFFICIENT_FUNDING,
)
from logic import bump, material_totals, cycle_ledger, sync_posture
from serializers import ser_material_order

bp = Blueprint("materials", __name__)

MATERIAL_STATUSES = ("ORDERED", "STAGED", "DELIVERED", "RETURNED")


@bp.post("/rebuild/material-orders")
def create_material_order():
    require_roles("AffiliateStaff")
    b = body()
    project_id = b.get("project_id")
    if project_id is None:
        raise_err(E_INVALID_REQUEST, 400, "project_id is required")
    project = get_or_404("projects", project_id, E_PROJECT_NOT_FOUND)
    if project["status"] not in ("PLANNING", "READY", "EVENT_SCHEDULED",
                                 "IN_BUILD"):
        raise_err(E_INVALID_STATE, 409,
                  "the project must be PLANNING, READY, EVENT_SCHEDULED or "
                  "IN_BUILD")
    supplier = opt_str(b, "supplier", default=None)
    lines = b.get("lines")
    if not isinstance(lines, list) or not lines:
        raise_err(E_INVALID_REQUEST, 400, "lines must be a non-empty array")
    cleaned = []
    for i, line in enumerate(lines):
        if not isinstance(line, dict):
            raise_err(E_INVALID_REQUEST, 400,
                      "line %d must be an object" % i)
        name = line.get("item_name")
        if not isinstance(name, str) or name == "":
            raise_err(E_INVALID_REQUEST, 400,
                      "line %d item_name is required" % i)
        qty = line.get("quantity")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty < 1:
            raise_err(E_INVALID_REQUEST, 400,
                      "line %d quantity must be an integer >= 1" % i)
        price = line.get("unit_price_dollars")
        if isinstance(price, bool) or not isinstance(price, (int, float)) \
                or price <= 0:
            raise_err(E_INVALID_REQUEST, 400,
                      "line %d unit_price_dollars must be > 0" % i)
        cleaned.append({"item_name": name, "quantity": qty,
                        "unit_price_dollars": price})
    subtotal, fee, total = material_totals(cleaned)
    cycle = STORES["funding_cycles"].get(project["funding_cycle_id"])
    if total > cycle_ledger(cycle)["available_cents"]:
        raise_err(E_INSUFFICIENT_FUNDING, 402,
                  "order total exceeds the cycle's available funding")
    rec = new_record("material_orders", {
        "project_id": project_id,
        "supplier": supplier,
        "lines": cleaned,
        "status": "ORDERED",
        "subtotal_cents": subtotal,
        "delivery_fee_cents": fee,
        "total_cents": total,
    }, now_iso)
    sync_posture(project)
    return ok_obj(ser_material_order(rec), 201)


@bp.get("/rebuild/material-orders")
def list_material_orders():
    require_roles("Any")
    recs = list(STORES["material_orders"].values())
    pid = request.args.get("project_id")
    if pid is not None:
        recs = [r for r in recs if r["project_id"] == pid]
    st = request.args.get("status")
    if st is not None:
        recs = [r for r in recs if r["status"] == st]
    return list_response(recs, ser_material_order)


@bp.get("/rebuild/material-orders/<orderId>")
def get_material_order(orderId):
    require_roles("Any")
    rec = get_or_404("material_orders", orderId, E_MATERIAL_ORDER_NOT_FOUND)
    return ok_obj(ser_material_order(rec))


@bp.patch("/rebuild/material-orders/<orderId>")
def patch_material_order(orderId):
    require_roles("AffiliateStaff")
    rec = get_or_404("material_orders", orderId, E_MATERIAL_ORDER_NOT_FOUND)
    b = body()
    if "status" not in b:
        raise_err(E_INVALID_REQUEST, 400, "status is required")
    target = b["status"]
    if not isinstance(target, str) or target not in MATERIAL_STATUSES:
        raise_err(E_INVALID_REQUEST, 400,
                  "status must be one of " + ", ".join(MATERIAL_STATUSES))
    if target == "STAGED":
        if rec["status"] != "ORDERED":
            raise_err(E_INVALID_STATE, 409, "order must be ORDERED to stage")
        rec["status"] = "STAGED"
    elif target == "DELIVERED":
        if rec["status"] != "STAGED":
            raise_err(E_INVALID_STATE, 409,
                      "order must be STAGED to deliver")
        rec["status"] = "DELIVERED"
    elif target == "RETURNED":
        if rec["status"] not in ("ORDERED", "STAGED", "DELIVERED"):
            raise_err(E_INVALID_STATE, 409,
                      "order cannot be returned from %s" % rec["status"])
        rec["status"] = "RETURNED"
    else:  # ORDERED is not a drivable target
        raise_err(E_INVALID_STATE, 409, "no transition to %s" % target)
    bump(rec)
    project = STORES["projects"].get(rec["project_id"])
    if project is not None:
        sync_posture(project)
    return ok_obj(ser_material_order(rec))
