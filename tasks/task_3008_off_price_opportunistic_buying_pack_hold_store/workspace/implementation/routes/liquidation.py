"""Liquidation orders: create, approve (provisional), execute (actual), cancel."""
from flask import Blueprint, request

import errors as err
from errors import ApiError
from db import db
from middleware import require
from response import success, success_list
from services.calc import (
    LIQ_REASONS, LIVE_SKU_STATUSES,
    get_body, validate_body, require_range, new_common, touch, get_or_404,
    find_by, paginate, serialize, round_half_up,
)

bp = Blueprint("liquidation", __name__)

LIQ_ROLES = ("PlanningLead", "StoreOpsLead")


def _affected_skus(order):
    line_ids = {l["id"] for l in db["lot_lines"].values()
                if l["lot_id"] == order["lot_id"]}
    return [s for s in db["store_skus"].values()
            if s["store_id"] == order["store_id"] and s["lot_line_id"] in line_ids
            and s["status"] in LIVE_SKU_STATUSES]


def _current_unit_basis(order):
    skus = _affected_skus(order)
    return skus[0]["current_price_cents"] if skus else 0


@bp.post("/liquidation-orders")
def create_liquidation_order():
    require(("PlanningLead",))
    vals = validate_body(get_body(required=True), {
        "store_id": ("str", True),
        "lot_id": ("str", True),
        "reason": ("enum", True, LIQ_REASONS),
        "recovery_rate_pct": ("float", True),
    })
    get_or_404("stores", vals["store_id"], "store not found")
    get_or_404("lots", vals["lot_id"], "lot not found")
    require_range(vals["recovery_rate_pct"], lo=0, hi=1, lo_exclusive=True,
                  field="recovery_rate_pct")
    order = new_common()
    order.update(vals)
    db["liquidation_orders"][order["id"]] = order
    order["expected_units"] = sum(s["units_on_hand"] for s in _affected_skus(order))
    order["actual_units"] = None
    order["recovery_value_cents"] = None
    order["status"] = "DRAFT"
    return success(serialize("liquidation_order", order), status=201)


@bp.get("/liquidation-orders")
def list_liquidation_orders():
    require(LIQ_ROLES)
    filters = {k: request.args.get(k) for k in ("store_id", "lot_id", "status", "reason")}
    page, limit, offset, total = paginate(list(db["liquidation_orders"].values()), filters)
    return success_list([serialize("liquidation_order", o) for o in page], limit, offset, total)


@bp.get("/liquidation-orders/<oid>")
def get_liquidation_order(oid):
    require(LIQ_ROLES)
    return success(serialize("liquidation_order", get_or_404("liquidation_orders", oid)))


@bp.post("/liquidation-orders/<oid>/approve")
def approve_liquidation_order(oid):
    require(("PlanningLead",))
    order = get_or_404("liquidation_orders", oid)
    get_body()
    if order["status"] != "DRAFT":
        raise err.invalid_state("only a DRAFT liquidation order can be approved")
    order["recovery_value_cents"] = round_half_up(
        order["expected_units"] * _current_unit_basis(order) * order["recovery_rate_pct"])
    order["status"] = "APPROVED"
    touch(order)
    return success(serialize("liquidation_order", order))


@bp.post("/liquidation-orders/<oid>/execute")
def execute_liquidation_order(oid):
    require(("StoreOpsLead",))
    order = get_or_404("liquidation_orders", oid)
    vals = validate_body(get_body(required=True), {"actual_units": ("int", True)})
    require_range(vals["actual_units"], lo=0, field="actual_units")
    if order["status"] != "APPROVED":
        raise err.invalid_state("only an APPROVED liquidation order can be executed")
    order["actual_units"] = vals["actual_units"]
    order["recovery_value_cents"] = round_half_up(
        order["actual_units"] * _current_unit_basis(order) * order["recovery_rate_pct"])
    for sku in _affected_skus(order):
        sku["units_on_hand"] = 0
        sku["status"] = "LIQUIDATED"
        touch(sku)
    order["status"] = "EXECUTED"
    touch(order)
    return success(serialize("liquidation_order", order))


@bp.post("/liquidation-orders/<oid>/cancel")
def cancel_liquidation_order(oid):
    require(("PlanningLead",))
    order = get_or_404("liquidation_orders", oid)
    get_body()
    if order["status"] != "DRAFT":
        raise err.invalid_state("only a DRAFT liquidation order can be cancelled")
    order["status"] = "CANCELLED"
    touch(order)
    return success(serialize("liquidation_order", order))
