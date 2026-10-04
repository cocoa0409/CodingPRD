"""Trial returns and warranty claims."""
from flask import Blueprint, request

import calculations as calc
from db import DB, parse_iso
from errors import ApiError, err_validation, not_found
from helpers import (
    body, new_entity, page, parse_pagination, public, req_field,
    require_enum, require_str, sorted_items, touch,
)
from middleware import authenticate, check_customer_ownership, require_roles
from response import success_list, success_object

bp = Blueprint("post_sale", __name__)

REFUND_DESTINATIONS = {"ORIGINAL_PAYMENT", "STORE_CREDIT"}
COMPONENT_CATEGORIES = {"CHAMBER", "PUMP", "ELECTRONICS", "STRUCTURAL"}
PRORATION_VARIANTS = {"TIME_BASED", "NIGHTS_USED"}
CONDITIONS = {"GOOD", "DAMAGED"}


def _get_order_or_404(order_id):
    order = DB.orders.get(order_id)
    if order is None:
        raise not_found("ERR_ORDER_NOT_FOUND", "order id does not resolve")
    return order


def _get_return_or_404(return_id):
    tr = DB.trial_returns.get(return_id)
    if tr is None:
        raise not_found("ERR_TRIAL_RETURN_NOT_FOUND", "trial return id does not resolve")
    return tr


def _get_claim_or_404(claim_id):
    c = DB.warranty_claims.get(claim_id)
    if c is None:
        raise not_found("ERR_WARRANTY_CLAIM_NOT_FOUND", "warranty claim id does not resolve")
    return c


def _pm_by_sku():
    return {pm["sku"]: pm for pm in DB.product_models.values()}


# ---------------------------------------------------------------- trial returns
@bp.post("/sleep/orders/<order_id>/trial-return")
def initiate_trial_return(order_id):
    role, uid = authenticate()
    require_roles(role, uid, {"Customer"})
    order = _get_order_or_404(order_id)
    check_customer_ownership(role, uid, order["customer_id"])
    data = body()
    if order["order_status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_STATE", 409, "order must be DELIVERED to start a trial return")
    # trial window
    clock = DB.clock.now()
    verified = parse_iso(order["trial_verified_at"])
    night_index = int((clock - verified).total_seconds() // 86400)
    if night_index > 99:
        raise ApiError("ERR_TRIAL_WINDOW_EXPIRED", 422,
                       "trial return initiated at night_index >= 100")
    reason = require_str(req_field(data, "reason"), "reason")
    destination = require_enum(req_field(data, "refund_destination"), "refund_destination", REFUND_DESTINATIONS)
    ent = new_entity({
        "order_id": order["id"],
        "reason": reason,
        "refund_destination": destination,
        "initiated_night_index": night_index,
        "condition": None,
        "depreciation_cents": None,
        "restocking_fee_cents": None,
        "refund_cents": None,
        "status": "INITIATED",
    })
    DB.trial_returns[ent["id"]] = ent
    return success_object(public(ent), 201)


@bp.get("/sleep/trial-returns/<return_id>")
def get_trial_return(return_id):
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin", "ServiceAgent", "Customer"})
    tr = _get_return_or_404(return_id)
    if role == "Customer":
        order = DB.orders.get(tr["order_id"])
        check_customer_ownership(role, uid, order["customer_id"] if order else None)
    return success_object(public(tr))


@bp.get("/sleep/trial-returns")
def list_trial_returns():
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin", "ServiceAgent", "Customer"})
    limit, offset = parse_pagination()
    items = list(DB.trial_returns.values())
    oid = request.args.get("order_id")
    if oid is not None:
        items = [t for t in items if t["order_id"] == oid]
    if role == "Customer":
        own_orders = {o["id"] for o in DB.orders.values() if o["customer_id"] == uid}
        items = [t for t in items if t["order_id"] in own_orders]
    items = sorted_items(items)
    total = len(items)
    return success_list([public(t) for t in page(items, limit, offset)], limit, offset, total)


@bp.post("/sleep/trial-returns/<return_id>/inspect")
def inspect_trial_return(return_id):
    role, uid = authenticate()
    require_roles(role, uid, {"ServiceAgent"})
    tr = _get_return_or_404(return_id)
    data = body()
    if tr["status"] != "INITIATED":
        raise ApiError("ERR_INVALID_STATE", 409, "trial return is not INITIATED")
    outcome = req_field(data, "outcome")
    if outcome not in ("APPROVED", "REJECTED"):
        raise err_validation("outcome must be APPROVED or REJECTED")
    condition = require_enum(req_field(data, "condition"), "condition", CONDITIONS)
    if outcome == "REJECTED":
        tr["status"] = "REJECTED"
        touch(tr)
        return success_object(public(tr))
    order = _get_order_or_404(tr["order_id"])
    dep, fee, refund = calc.restocking_refund(
        order["line_items"], _pm_by_sku(), condition, order["total_paid_cents"]
    )
    tr["condition"] = condition
    tr["depreciation_cents"] = dep
    tr["restocking_fee_cents"] = fee
    tr["refund_cents"] = refund
    tr["status"] = "REFUNDED"
    touch(tr)
    # cascade 1: order DELIVERED -> RETURNED; payment_status -> REFUNDED
    if order["order_status"] == "DELIVERED":
        order["order_status"] = "RETURNED"
    order["payment_status"] = "REFUNDED"
    touch(order)
    # cascade 2: ACTIVE financing plan settles early with credit memo
    settled = 0
    for plan in DB.financing_plans.values():
        if plan["order_id"] == order["id"] and plan["status"] == "ACTIVE":
            settled = min(refund, plan["balance_cents"])
            plan["settled_credit_cents"] = settled
            plan["balance_cents"] -= settled
            plan["status"] = "SETTLED_EARLY"
            touch(plan)
            break
    # STORE_CREDIT destination credits the remainder to the customer
    if tr["refund_destination"] == "STORE_CREDIT":
        customer = DB.customers.get(order["customer_id"])
        if customer is not None:
            customer["store_credit_cents"] += refund - settled
            touch(customer)
    return success_object(public(tr))


# ---------------------------------------------------------------- warranty claims
@bp.post("/sleep/warranty-claims")
def file_warranty_claim():
    role, uid = authenticate()
    require_roles(role, uid, {"Customer"})
    data = body()
    order_id = require_str(req_field(data, "order_id"), "order_id")
    device_id = require_str(req_field(data, "device_id"), "device_id")
    component = require_enum(req_field(data, "component_category"), "component_category", COMPONENT_CATEGORIES)
    variant = require_enum(req_field(data, "proration_variant"), "proration_variant", PRORATION_VARIANTS)
    description = require_str(req_field(data, "description"), "description")
    order = DB.orders.get(order_id)
    if order is None:
        raise not_found("ERR_ORDER_NOT_FOUND", "order id does not resolve")
    check_customer_ownership(role, uid, order["customer_id"])
    device = DB.devices.get(device_id)
    if device is None:
        raise not_found("ERR_DEVICE_NOT_FOUND", "device id does not resolve")
    if device["order_id"] != order_id:
        raise ApiError("ERR_DEVICE_NOT_ON_ORDER", 422,
                       "warranty claim device not registered under the order")
    # months in service snapshot
    clock = DB.clock.now()
    if order.get("trial_verified_at") is not None:
        days = (clock - parse_iso(order["trial_verified_at"])).total_seconds() // 86400
        months_in_service = int(days // 30)
    else:
        months_in_service = 0
    if months_in_service >= calc.WARRANTY_MONTHS[component]:
        raise ApiError("ERR_WARRANTY_EXPIRED", 422,
                       "months_in_service >= warranty_months for component")
    ent = new_entity({
        "order_id": order_id,
        "device_id": device_id,
        "component_category": component,
        "proration_variant": variant,
        "description": description,
        "months_in_service": months_in_service,
        "final_nights_used": device.get("final_nights_count", 0),
        "credit_cents": None,
        "applied_to": None,
        "status": "FILED",
    })
    DB.warranty_claims[ent["id"]] = ent
    return success_object(public(ent), 201)


@bp.get("/sleep/warranty-claims/<claim_id>")
def get_warranty_claim(claim_id):
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin", "ServiceAgent", "Customer"})
    claim = _get_claim_or_404(claim_id)
    if role == "Customer":
        order = DB.orders.get(claim["order_id"])
        check_customer_ownership(role, uid, order["customer_id"] if order else None)
    return success_object(public(claim))


@bp.get("/sleep/warranty-claims")
def list_warranty_claims():
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin", "ServiceAgent", "Customer"})
    limit, offset = parse_pagination()
    items = list(DB.warranty_claims.values())
    for key in ("order_id", "device_id"):
        v = request.args.get(key)
        if v is not None:
            items = [c for c in items if c.get(key) == v]
    if role == "Customer":
        own_orders = {o["id"] for o in DB.orders.values() if o["customer_id"] == uid}
        items = [c for c in items if c["order_id"] in own_orders]
    items = sorted_items(items)
    total = len(items)
    return success_list([public(c) for c in page(items, limit, offset)], limit, offset, total)


def _apply_claim_credit(claim, order):
    base = calc.warranty_base_price(order["line_items"], _pm_by_sku(), claim["component_category"])
    credit = calc.prorated_warranty_credit(
        base, claim["component_category"], claim["proration_variant"],
        claim["months_in_service"], claim["final_nights_used"],
    )
    claim["credit_cents"] = credit
    active_plan = next(
        (p for p in DB.financing_plans.values()
         if p["order_id"] == order["id"] and p["status"] == "ACTIVE"),
        None,
    )
    if active_plan is not None:
        active_plan["balance_cents"] -= credit
        touch(active_plan)
        claim["applied_to"] = "FINANCING_BALANCE"
    else:
        customer = DB.customers.get(order["customer_id"])
        if customer is not None:
            customer["store_credit_cents"] += credit
            touch(customer)
        claim["applied_to"] = "STORE_CREDIT"


@bp.post("/sleep/warranty-claims/<claim_id>/review")
def review_warranty_claim(claim_id):
    role, uid = authenticate()
    require_roles(role, uid, {"ServiceAgent"})
    claim = _get_claim_or_404(claim_id)
    data = body()
    if claim["status"] not in ("FILED", "APPEALED"):
        raise ApiError("ERR_INVALID_STATE", 409, "claim is not FILED or APPEALED")
    decision = req_field(data, "decision")
    if decision not in ("APPROVE", "DENY"):
        raise err_validation("decision must be APPROVE or DENY")
    if decision == "DENY":
        claim["status"] = "DENIED"
        if "denial_reason" in data:
            claim["denial_reason"] = data["denial_reason"]
        touch(claim)
        return success_object(public(claim))
    order = _get_order_or_404(claim["order_id"])
    if order["order_status"] in ("CANCELLED", "RETURNED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "order is CANCELLED or RETURNED; approval refused")
    _apply_claim_credit(claim, order)
    claim["status"] = "APPROVED"
    touch(claim)
    return success_object(public(claim))


@bp.post("/sleep/warranty-claims/<claim_id>/appeal")
def appeal_warranty_claim(claim_id):
    role, uid = authenticate()
    require_roles(role, uid, {"Customer"})
    claim = _get_claim_or_404(claim_id)
    order = DB.orders.get(claim["order_id"])
    check_customer_ownership(role, uid, order["customer_id"] if order else None)
    if claim["status"] != "DENIED":
        raise ApiError("ERR_INVALID_STATE", 409, "only DENIED claims may be appealed")
    claim["status"] = "APPEALED"
    touch(claim)
    return success_object(public(claim))
