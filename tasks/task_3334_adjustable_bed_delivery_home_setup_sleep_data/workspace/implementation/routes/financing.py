"""Financing plans and the logical clock endpoint."""
from decimal import Decimal

from flask import Blueprint, request

import calculations as calc
from db import DB, parse_iso
from errors import ApiError, err_validation, not_found
from helpers import (
    body, new_entity, opt_field, page, parse_pagination, public, req_field,
    require_enum, require_int, sorted_items, touch,
)
from middleware import authenticate, check_customer_ownership, require_roles
from response import success_list, success_object
from sweeps import run_clock_sweeps

bp = Blueprint("financing", __name__)

OFFER_TYPES = {"ZERO_APR", "DEFERRED_INTEREST", "STANDARD"}
ALLOWED_TERMS = {12, 24, 36}
MAX_PRINCIPAL_CENTS = 500000


def _get_plan_or_404(plan_id):
    p = DB.financing_plans.get(plan_id)
    if p is None:
        raise not_found("ERR_FINANCING_PLAN_NOT_FOUND", "financing plan id does not resolve")
    return p


def _get_order_or_404(order_id):
    order = DB.orders.get(order_id)
    if order is None:
        raise not_found("ERR_ORDER_NOT_FOUND", "order id does not resolve")
    return order


def _installments_due(plan):
    from sweeps import _installments_due as due
    return due(plan, DB.clock.now())


def _paid_installments(plan):
    mpc = plan["monthly_payment_cents"]
    if mpc <= 0:
        return 0
    return plan["paid_cents"] // mpc


def _cure_check(plan):
    """After a payment on a DELINQUENT plan: cure when paid >= due - 1."""
    if plan["status"] != "DELINQUENT":
        return
    due = _installments_due(plan)
    paid = _paid_installments(plan)
    if paid >= due - 1:
        plan["status"] = "ACTIVE"
        touch(plan)


@bp.post("/sleep/financing-plans")
def create_financing_plan():
    role, uid = authenticate()
    require_roles(role, uid, {"FinanceAgent"})
    data = body()
    order_id = req_field(data, "order_id")
    if not isinstance(order_id, str):
        raise err_validation("order_id must be a string")
    offer_type = require_enum(req_field(data, "offer_type"), "offer_type", OFFER_TYPES)
    term_months = require_int(req_field(data, "term_months"), "term_months")
    apr_bps = require_int(req_field(data, "apr_bps"), "apr_bps")
    down_payment = opt_field(data, "down_payment_cents", 0)
    down_payment = require_int(down_payment, "down_payment_cents")
    order = _get_order_or_404(order_id)
    if order["order_status"] in ("CANCELLED", "CLOSED", "RETURNED"):
        raise ApiError("ERR_ORDER_ALREADY_TERMINAL", 409, "order is terminal")
    if order["order_status"] != "PLACED":
        raise ApiError("ERR_INVALID_STATE", 409, "financing may only attach to a PLACED order")
    if term_months not in ALLOWED_TERMS:
        raise ApiError("ERR_PROMO_TERM_INVALID", 422, "term_months must be 12, 24, or 36")
    if offer_type == "ZERO_APR" and apr_bps != 0:
        raise ApiError("ERR_PROMO_TERM_INVALID", 422, "ZERO_APR requires apr_bps == 0")
    if offer_type == "DEFERRED_INTEREST" and apr_bps <= 0:
        raise ApiError("ERR_PROMO_TERM_INVALID", 422, "DEFERRED_INTEREST requires apr_bps > 0")
    principal = order["total_due_cents"] - down_payment
    if principal > MAX_PRINCIPAL_CENTS:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 402, "principal exceeds 500000")
    if offer_type == "DEFERRED_INTEREST":
        floor = calc.round_half_up(Decimal("0.10") * order["total_due_cents"])
        if down_payment < floor:
            raise ApiError("ERR_DOWN_PAYMENT_INSUFFICIENT", 402,
                           "DEFERRED_INTEREST down payment below 10% floor")
    monthly, promo_months = calc.financing_schedule(offer_type, principal, term_months, apr_bps)
    ent = new_entity({
        "order_id": order["id"],
        "offer_type": offer_type,
        "down_payment_cents": down_payment,
        "term_months": term_months,
        "apr_bps": apr_bps,
        "principal_cents": principal,
        "monthly_payment_cents": monthly,
        "promo_months": promo_months,
        "paid_cents": 0,
        "balance_cents": principal,
        "retro_interest_posted": False,
        "settled_credit_cents": 0,
        "activated_at": None,
        "status": "OFFERED",
    })
    DB.financing_plans[ent["id"]] = ent
    return success_object(public(ent), 201)


@bp.get("/sleep/financing-plans/<plan_id>")
def get_financing_plan(plan_id):
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin", "FinanceAgent", "ServiceAgent", "Customer"})
    plan = _get_plan_or_404(plan_id)
    if role == "Customer":
        order = DB.orders.get(plan["order_id"])
        check_customer_ownership(role, uid, order["customer_id"] if order else None)
    return success_object(public(plan))


@bp.get("/sleep/financing-plans")
def list_financing_plans():
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin", "FinanceAgent", "ServiceAgent", "Customer"})
    limit, offset = parse_pagination()
    items = list(DB.financing_plans.values())
    oid = request.args.get("order_id")
    if oid is not None:
        items = [p for p in items if p["order_id"] == oid]
    if role == "Customer":
        own_orders = {o["id"] for o in DB.orders.values() if o["customer_id"] == uid}
        items = [p for p in items if p["order_id"] in own_orders]
    items = sorted_items(items)
    total = len(items)
    return success_list([public(p) for p in page(items, limit, offset)], limit, offset, total)


@bp.post("/sleep/financing-plans/<plan_id>/accept")
def accept_financing_plan(plan_id):
    role, uid = authenticate()
    require_roles(role, uid, {"Customer"})
    plan = _get_plan_or_404(plan_id)
    order = DB.orders.get(plan["order_id"])
    check_customer_ownership(role, uid, order["customer_id"] if order else None)
    if plan["status"] != "OFFERED":
        raise ApiError("ERR_INVALID_STATE", 409, "only OFFERED plans may be accepted")
    plan["status"] = "ACCEPTED"
    touch(plan)
    return success_object(public(plan))


@bp.post("/sleep/financing-plans/<plan_id>/payments")
def record_payment(plan_id):
    role, uid = authenticate()
    require_roles(role, uid, {"FinanceAgent"})
    plan = _get_plan_or_404(plan_id)
    data = body()
    if plan["status"] not in ("ACTIVE", "DELINQUENT"):
        raise ApiError("ERR_INVALID_STATE", 409, "payments only on ACTIVE or DELINQUENT plans")
    amount = require_int(req_field(data, "amount_cents"), "amount_cents")
    if amount < 1 or amount > plan["balance_cents"]:
        raise ApiError("ERR_PAYMENT_EXCEEDS_BALANCE", 422,
                       "payment amount must be >= 1 and <= balance_cents")
    plan["paid_cents"] += amount
    plan["balance_cents"] -= amount
    if plan["balance_cents"] == 0 and plan["status"] == "ACTIVE":
        plan["status"] = "PAID_OFF"
    touch(plan)
    if plan["status"] == "DELINQUENT":
        _cure_check(plan)
    return success_object(public(plan), 201)


# ---------------------------------------------------------------- logical clock
@bp.post("/_clock/set_current_utc")
def set_clock():
    role, uid = authenticate()
    require_roles(role, uid, {"PlatformAdmin"})
    data = body()
    raw = req_field(data, "to_iso8601")
    if not isinstance(raw, str):
        raise err_validation("to_iso8601 must be an ISO 8601 string")
    try:
        dt = parse_iso(raw)
    except (ValueError, TypeError):
        raise err_validation("to_iso8601 must be an ISO 8601 timestamp")
    DB.clock.set(dt)
    run_clock_sweeps(dt)
    return success_object({})
