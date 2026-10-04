"""Reagent orders: submit with locked layered pricing, read, fulfill/cancel."""
from flask import Blueprint, request

import db
import ser
import services
import util
from constants import PRICE_TABLE
from errors import err

bp = Blueprint("reagent_orders", __name__)


def _load_order(oid):
    o = db.orders.get(oid)
    if o is None:
        raise err("ERR_ORDER_NOT_FOUND", "reagent order does not exist")
    return o


@bp.post("/api/reagent-orders")
def create_order():
    uid, role = util.auth()
    util.require(role, ["ClinicManager"])
    b = util.body()

    # Tier 3 ownership: body clinic_id must equal X-User-ID.
    clinic_id = b.get("clinic_id")
    if clinic_id is not None and uid != clinic_id:
        raise err("ERR_CLINIC_OWNERSHIP_MISMATCH",
                  "X-User-ID must equal the body clinic_id")

    # Tier 4 existence, in declared input order: clinic_id then agreement_id.
    if clinic_id is None:
        raise err("ERR_INVALID_REQUEST", "clinic_id is required")
    clinic = db.clinics.get(clinic_id)
    if clinic is None:
        raise err("ERR_CLINIC_NOT_FOUND", "clinic_id does not exist")
    agreement_id = b.get("agreement_id")
    if agreement_id is None:
        raise err("ERR_INVALID_REQUEST", "agreement_id is required")
    ag = db.agreements.get(agreement_id)
    if ag is None:
        raise err("ERR_AGREEMENT_NOT_FOUND", "agreement_id does not exist")

    # Tier 5 input shape.
    order_month = b.get("order_month")
    if not isinstance(order_month, str) or not util.MONTH_RE.match(order_month):
        raise err("ERR_INVALID_REQUEST", "order_month must be YYYY-MM")
    lines = b.get("lines")
    if not isinstance(lines, list) or not lines:
        raise err("ERR_INVALID_REQUEST", "lines must be a non-empty array")
    for ln in lines:
        if not isinstance(ln, dict):
            raise err("ERR_INVALID_REQUEST", "each line must be an object")
        sku = ln.get("sku")
        if sku not in PRICE_TABLE:
            raise err("ERR_UNKNOWN_SKU", f"unknown sku: {sku}")
        qty = ln.get("quantity")
        if not util.is_int(qty) or qty <= 0:
            raise err("ERR_INVALID_REQUEST",
                      "line quantity must be a strictly positive integer")
    months = util.term_months(ag["_start"], ag["term_months"])
    if order_month not in months:
        raise err("ERR_INVALID_REQUEST",
                  "order_month must fall within the agreement term months")

    # Tier 6 state.
    if clinic["status"] != "ACTIVE":
        raise err("ERR_CLINIC_NOT_ACTIVE", "the clinic must be ACTIVE")
    if ag["status"] not in ("ACTIVE", "RENEGOTIATION"):
        raise err("ERR_AGREEMENT_INVALID_STATE",
                  "the agreement must be ACTIVE or RENEGOTIATION")

    now = db.now()
    detail, final_total, list_total = services.price_order(
        clinic, ag, lines, now)
    o = services.stamp({
        "clinic_id": clinic_id,
        "agreement_id": agreement_id,
        "order_month": order_month,
        "lines": lines,
        "pricing_detail": detail,
        "list_total_cents": list_total,
        "final_total_cents": final_total,
        "_fulfilled_at": None,
        "status": "SUBMITTED",
    })
    db.orders[o["id"]] = o
    return util.ok(ser.order(o), code=201)


@bp.get("/api/reagent-orders/<oid>")
def get_order(oid):
    util.auth()
    return util.ok(ser.order(_load_order(oid)))


@bp.get("/api/reagent-orders")
def list_orders():
    util.auth()
    items = util.sorted_items(db.orders.values())
    cid = request.args.get("clinic_id")
    if cid is not None:
        items = [o for o in items if o["clinic_id"] == cid]
    gid = request.args.get("agreement_id")
    if gid is not None:
        items = [o for o in items if o["agreement_id"] == gid]
    st = request.args.get("status")
    if st is not None:
        items = [o for o in items if o["status"] == st]
    return util.paginate([ser.order(o) for o in items])


@bp.patch("/api/reagent-orders/<oid>")
def patch_order(oid):
    uid, role = util.auth()
    util.require(role, ["ClinicManager"])
    o = _load_order(oid)
    if uid != o["clinic_id"]:
        raise err("ERR_CLINIC_OWNERSHIP_MISMATCH",
                  "X-User-ID must equal the order's clinic_id")
    b = util.body()
    target = b.get("status")
    if target not in ("FULFILLED", "CANCELLED"):
        raise err("ERR_INVALID_REQUEST", "status must be FULFILLED or CANCELLED")

    if o["status"] != "SUBMITTED":
        raise err("ERR_ORDER_INVALID_STATE",
                  "the order must be SUBMITTED to drive it")
    if target == "FULFILLED":
        clinic = db.clinics.get(o["clinic_id"])
        if clinic is None or clinic["status"] != "ACTIVE":
            raise err("ERR_CLINIC_NOT_ACTIVE", "the clinic must be ACTIVE")
        ag = db.agreements.get(o["agreement_id"])
        if ag is None or ag["status"] not in ("ACTIVE", "RENEGOTIATION"):
            raise err("ERR_AGREEMENT_INVALID_STATE",
                      "the agreement must be ACTIVE or RENEGOTIATION")
        o["status"] = "FULFILLED"
        o["_fulfilled_at"] = db.now()
        services.bump(o)
    else:
        o["status"] = "CANCELLED"
        services.bump(o)
    return util.ok(ser.order(o))
