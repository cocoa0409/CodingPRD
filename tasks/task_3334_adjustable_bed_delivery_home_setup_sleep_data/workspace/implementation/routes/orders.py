"""Order endpoints: create/read/list/patch/confirm/cancel."""
from flask import Blueprint, request

import calculations as calc
from db import DB
from errors import ApiError, err_validation, not_found
from helpers import (
    body, new_entity, page, parse_pagination, public, req_field,
    require_enum, require_int, require_str, sorted_items, touch,
)
from middleware import authenticate, check_customer_ownership, require_roles
from response import success_list, success_object
from sweeps import promote_waitlist

bp = Blueprint("orders", __name__)

ORDER_TERMINAL = {"CANCELLED", "CLOSED", "RETURNED"}
PAYMENT_METHODS = {"PAY_IN_FULL", "FINANCING"}


def _get_order_or_404(order_id):
    order = DB.orders.get(order_id)
    if order is None:
        raise not_found("ERR_ORDER_NOT_FOUND", "order id does not resolve")
    return order


def _expand_line_items(line_items):
    if not isinstance(line_items, list) or len(line_items) == 0:
        raise err_validation("line_items must be a non-empty array")
    expanded = []
    for item in line_items:
        if not isinstance(item, dict):
            raise err_validation("each line item must be an object")
        sku = item.get("sku")
        qty = item.get("qty")
        if not isinstance(sku, str):
            raise err_validation("line item sku must be a string")
        if isinstance(qty, bool) or not isinstance(qty, int):
            raise err_validation("line item qty must be an integer")
        pm = next((p for p in DB.product_models.values() if p["sku"] == sku), None)
        if pm is None:
            raise not_found("ERR_PRODUCT_MODEL_NOT_FOUND", "line_items sku matches no ProductModel")
        expanded.append({"sku": sku, "qty": qty, "unit_price_cents": pm["price_cents"]})
    return expanded


def _reprice(order):
    totals = calc.compute_order_totals(order["line_items"])
    order["subtotal_cents"] = totals["subtotal_cents"]
    order["discount_cents"] = totals["discount_cents"]
    order["delivery_fee_cents"] = totals["delivery_fee_cents"]
    order["total_due_cents"] = totals["total_due_cents"]


@bp.post("/sleep/orders")
def create_order():
    role, uid = authenticate()
    require_roles(role, uid, {"Customer", "SalesAssociate"})
    data = body()
    customer_id = require_str(req_field(data, "customer_id"), "customer_id")
    fit_assessment_id = require_str(req_field(data, "fit_assessment_id"), "fit_assessment_id")
    check_customer_ownership(role, uid, customer_id)
    if customer_id not in DB.customers:
        raise not_found("ERR_CUSTOMER_NOT_FOUND", "customer id does not resolve")
    fa = DB.fit_assessments.get(fit_assessment_id)
    if fa is None:
        raise not_found("ERR_FIT_ASSESSMENT_NOT_FOUND", "fit assessment id does not resolve")
    line_items = req_field(data, "line_items")
    expanded = _expand_line_items(line_items)
    if fa["customer_id"] != customer_id or fa["status"] != "COMPLETED":
        raise ApiError("ERR_FIT_ASSESSMENT_MISMATCH", 422,
                       "fit assessment belongs to another customer or is not COMPLETED")
    order = new_entity({
        "customer_id": customer_id,
        "fit_assessment_id": fit_assessment_id,
        "line_items": expanded,
        "subtotal_cents": 0,
        "discount_cents": 0,
        "delivery_fee_cents": 0,
        "total_due_cents": 0,
        "total_paid_cents": 0,
        "order_status": "PLACED",
        "payment_status": "UNPAID",
        "trial_verified_at": None,
    })
    _reprice(order)
    DB.orders[order["id"]] = order
    return success_object(public(order), 201)


@bp.get("/sleep/orders/<order_id>")
def get_order(order_id):
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin", "SalesAssociate", "ServiceAgent", "FinanceAgent", "Customer"})
    order = _get_order_or_404(order_id)
    check_customer_ownership(role, uid, order["customer_id"])
    return success_object(public(order))


@bp.get("/sleep/orders")
def list_orders():
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin", "SalesAssociate", "ServiceAgent", "FinanceAgent"})
    limit, offset = parse_pagination()
    items = list(DB.orders.values())
    for key in ("customer_id", "fit_assessment_id"):
        v = request.args.get(key)
        if v is not None:
            items = [o for o in items if o.get(key) == v]
    items = sorted_items(items)
    total = len(items)
    return success_list([public(o) for o in page(items, limit, offset)], limit, offset, total)


@bp.patch("/sleep/orders/<order_id>")
def patch_order(order_id):
    role, uid = authenticate()
    require_roles(role, uid, {"Customer", "SalesAssociate"})
    order = _get_order_or_404(order_id)
    check_customer_ownership(role, uid, order["customer_id"])
    data = body()
    if order["order_status"] in ORDER_TERMINAL:
        raise ApiError("ERR_ORDER_ALREADY_TERMINAL", 409, "order is terminal")
    if order["order_status"] != "PLACED":
        raise ApiError("ERR_INVALID_STATE", 409, "only PLACED orders may be patched")
    expected = data.get("expected_order_version")
    if expected is not None:
        expected = require_int(expected, "expected_order_version")
        if expected != order["version"]:
            raise ApiError("ERR_STALE_VERSION", 412, "expected_order_version mismatch")
    line_items = req_field(data, "line_items")
    order["line_items"] = _expand_line_items(line_items)
    _reprice(order)
    touch(order)
    return success_object(public(order))


@bp.post("/sleep/orders/<order_id>/confirm")
def confirm_order(order_id):
    role, uid = authenticate()
    require_roles(role, uid, {"SalesAssociate"})
    order = _get_order_or_404(order_id)
    data = body()
    if order["order_status"] in ORDER_TERMINAL:
        raise ApiError("ERR_ORDER_ALREADY_TERMINAL", 409, "order is terminal")
    if order["order_status"] != "PLACED":
        raise ApiError("ERR_INVALID_STATE", 409, "order is not PLACED")
    payment_method = require_enum(req_field(data, "payment_method"), "payment_method", PAYMENT_METHODS)
    if payment_method == "FINANCING":
        plan_id = data.get("financing_plan_id")
        if plan_id is None:
            raise err_validation("financing_plan_id is required for FINANCING")
        plan = DB.financing_plans.get(plan_id)
        if plan is None:
            raise not_found("ERR_FINANCING_PLAN_NOT_FOUND", "financing plan id does not resolve")
        if plan["order_id"] != order["id"] or plan["status"] != "ACCEPTED":
            raise ApiError("ERR_INVALID_STATE", 409,
                           "financing plan must be ACCEPTED for this order")
        order["payment_status"] = "FINANCED"
        plan["status"] = "ACTIVE"
        plan["activated_at"] = DB.clock.now_iso()
        touch(plan)
    else:
        order["payment_status"] = "PAID"
    order["total_paid_cents"] = order["total_due_cents"]
    order["order_status"] = "CONFIRMED"
    touch(order)
    return success_object(public(order))


@bp.post("/sleep/orders/<order_id>/cancel")
def cancel_order(order_id):
    role, uid = authenticate()
    require_roles(role, uid, {"Customer", "SalesAssociate"})
    order = _get_order_or_404(order_id)
    check_customer_ownership(role, uid, order["customer_id"])
    if order["order_status"] in ORDER_TERMINAL:
        raise ApiError("ERR_ORDER_ALREADY_TERMINAL", 409, "order is terminal")
    if order["order_status"] not in ("PLACED", "CONFIRMED", "FULFILLING"):
        raise ApiError("ERR_INVALID_STATE", 409, "order cannot be cancelled from this state")
    if order["order_status"] in ("CONFIRMED", "FULFILLING"):
        verified = any(
            v["order_id"] == order["id"] and v["status"] == "VERIFIED"
            for v in DB.delivery_visits.values()
        )
        if verified:
            raise ApiError("ERR_INVALID_STATE", 409,
                           "a verified delivery visit blocks cancellation")
    # Cascade links 1-2: cancel non-terminal visits, release slots for SCHEDULED
    freed_windows = []
    for visit in list(DB.delivery_visits.values()):
        if visit["order_id"] != order["id"]:
            continue
        if visit["status"] in ("SCHEDULED", "WAITLISTED", "FAILED_SETUP"):
            if visit["status"] == "SCHEDULED":
                window = DB.delivery_windows.get(visit["delivery_window_id"])
                if window is not None:
                    window["reserved_slots"] -= visit["slot_need"]
                    touch(window)
                    freed_windows.append(window)
            visit["status"] = "CANCELLED"
            touch(visit)
    # Cascade link 3: waitlist promotion on each freed window
    for window in freed_windows:
        promote_waitlist(window)
    # Void financing
    for plan in list(DB.financing_plans.values()):
        if plan["order_id"] != order["id"]:
            continue
        if plan["status"] == "ACCEPTED":
            plan["status"] = "VOIDED"
            touch(plan)
        elif plan["status"] == "ACTIVE" and order["order_status"] in ("CONFIRMED", "FULFILLING"):
            plan["status"] = "VOIDED"
            touch(plan)
    if order["order_status"] in ("CONFIRMED", "FULFILLING") and order["payment_status"] in ("PAID", "FINANCED"):
        order["payment_status"] = "REFUNDED"
    order["order_status"] = "CANCELLED"
    touch(order)
    return success_object(public(order))
