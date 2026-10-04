"""Acquisition order routes with OCC and lifecycle transitions."""
from flask import Blueprint, request
from db import stores
from middleware import require_roles
from response import success, paginate
from engine import (
    new_id, now, touch_common, require_body, req_field, opt_field,
    get_order, serialize, recompute_fund, ERR_FUND_NOT_FOUND_SPEC,
)
from lending import fulfill_order
from errors import (
    err, ERR_ORDER_NOT_FOUND, ERR_REFERENCE_NOT_FOUND, ERR_FORBIDDEN,
    ERR_ORDER_INVALID_STATE, ERR_FUND_CLOSED, ERR_ORDER_OUTSIDE_FISCAL_PERIOD,
    ERR_BUDGET_EXCEEDED, ERR_STALE_FUND_VERSION,
    ERR_SIMULTANEOUS_USE_NOT_ALLOWED, ERR_INVALID_REQUEST,
)

bp = Blueprint("orders", __name__)

MODELS = ("OCOU", "METERED_TIME", "METERED_CIRC", "COST_PER_CIRC", "SIMULTANEOUS_USE")


def _estimate(model, copies, prepaid, title):
    if model == "OCOU":
        return copies * title["price_ocou_cents"]
    if model == "METERED_TIME":
        return title["metered_time_price_cents"]
    if model == "METERED_CIRC":
        return title["metered_circ_price_cents"]
    if model == "COST_PER_CIRC":
        return prepaid
    return title["simultaneous_use_price_cents"]


def _validate_terms(model, copies, prepaid, title):
    if model == "SIMULTANEOUS_USE" and not title["simultaneous_use_allowed"]:
        raise err(ERR_SIMULTANEOUS_USE_NOT_ALLOWED,
                  "SIMULTANEOUS_USE order on a title without simultaneous_use_allowed")
    if model == "OCOU":
        if copies is None or copies < 1:
            raise err(ERR_INVALID_REQUEST, "OCOU orders require copies >= 1")
    else:
        if copies is not None and copies != 1:
            raise err(ERR_INVALID_REQUEST, "non-OCOU orders must have copies == 1")
    if model == "COST_PER_CIRC" and prepaid is None:
        raise err(ERR_INVALID_REQUEST, "COST_PER_CIRC orders require prepaid_balance_cents")
    if model != "COST_PER_CIRC" and prepaid is not None:
        raise err(ERR_INVALID_REQUEST, "prepaid_balance_cents applies only to COST_PER_CIRC")


def _own_order(oid, uid):
    o = get_order(oid, ERR_ORDER_NOT_FOUND)
    if uid != o["library_id"]:
        raise err(ERR_FORBIDDEN, "LibraryAdmin may only manage their own library's orders")
    return o


@bp.post("/lending/acquisition-orders")
def create_order():
    body = require_body()
    library_id = req_field(body, "library_id", (str,))
    fund_id = req_field(body, "budget_fund_id", (str,))
    title_id = req_field(body, "title_id", (str,))
    model = req_field(body, "model", (str,), enums=MODELS)
    expected = req_field(body, "expected_budget_fund_version", (int,))
    copies = opt_field(body, "copies", (int,), default=None)
    prepaid = opt_field(body, "prepaid_balance_cents", (int,), default=None)
    role, uid = require_roles({"LibraryAdmin"})
    if uid != library_id:
        raise err(ERR_FORBIDDEN, "LibraryAdmin may only create orders for their own library")
    if library_id not in stores["libraries"]:
        raise err(ERR_REFERENCE_NOT_FOUND, "library_id does not resolve")
    fund = stores["funds"].get(fund_id)
    if fund is None:
        raise err(ERR_REFERENCE_NOT_FOUND, "budget_fund_id does not resolve")
    title = stores["titles"].get(title_id)
    if title is None:
        raise err(ERR_REFERENCE_NOT_FOUND, "title_id does not resolve")
    if expected != fund["version"]:
        raise err(ERR_STALE_FUND_VERSION, "stale budget fund version")
    if fund["library_id"] != library_id:
        raise err(ERR_FUND_NOT_FOUND_SPEC, "budget fund does not belong to this library")
    if copies is None:
        copies = 1
    _validate_terms(model, copies, prepaid, title)
    order = {
        "id": new_id(),
        "library_id": library_id,
        "budget_fund_id": fund_id,
        "title_id": title_id,
        "model": model,
        "copies": copies,
        "prepaid_balance_cents": prepaid,
        "estimated_cost_cents": _estimate(model, copies, prepaid, title),
        "invoiced_cost_cents": None,
        "origin": "MANUAL",
        "status": "DRAFT",
    }
    touch_common(order, created=True)
    order["_seq"] = len(stores["orders"])
    stores["orders"][order["id"]] = order
    touch_common(fund)
    recompute_fund(fund)
    return success(serialize(order), 201)


@bp.get("/lending/acquisition-orders")
def list_orders():
    require_roles({"ConsortiumAdmin", "LibraryAdmin", "SystemAnalyst"})
    items = list(stores["orders"].values())
    for key in ("library_id", "budget_fund_id", "title_id", "status"):
        v = request.args.get(key)
        if v is not None:
            items = [o for o in items if str(o.get(key)) == v]
    items.sort(key=lambda o: (o["created_at"], o["_seq"]))
    page, meta = paginate([serialize(o) for o in items], request.args)
    return success(page, 200, meta)


@bp.get("/lending/acquisition-orders/<oid>")
def read_order(oid):
    require_roles({"ConsortiumAdmin", "LibraryAdmin", "SystemAnalyst"})
    o = get_order(oid, ERR_ORDER_NOT_FOUND)
    return success(serialize(o))


@bp.post("/lending/acquisition-orders/<oid>/propose")
def propose_order(oid):
    role, uid = require_roles({"LibraryAdmin"})
    o = _own_order(oid, uid)
    if o["status"] != "DRAFT":
        raise err(ERR_ORDER_INVALID_STATE, "order is not DRAFT")
    o["status"] = "PROPOSED"
    touch_common(o)
    return success(serialize(o))


@bp.post("/lending/acquisition-orders/<oid>/approve")
def approve_order(oid):
    role, uid = require_roles({"LibraryAdmin"})
    o = _own_order(oid, uid)
    if o["status"] != "PROPOSED":
        raise err(ERR_ORDER_INVALID_STATE, "order is not PROPOSED")
    fund = stores["funds"][o["budget_fund_id"]]
    if fund["status"] != "OPEN":
        raise err(ERR_FUND_CLOSED, "fund is not OPEN")
    if not (fund["_period_start"] <= now() < fund["_period_end"]):
        raise err(ERR_ORDER_OUTSIDE_FISCAL_PERIOD, "current time is outside the fund period")
    recompute_fund(fund)
    if o["estimated_cost_cents"] > fund["available_committed_cents"]:
        raise err(ERR_BUDGET_EXCEEDED, "estimated cost exceeds available committed budget")
    o["status"] = "APPROVED"
    touch_common(o)
    touch_common(fund)
    recompute_fund(fund)
    return success(serialize(o))


@bp.post("/lending/acquisition-orders/<oid>/reject")
def reject_order(oid):
    role, uid = require_roles({"LibraryAdmin"})
    o = _own_order(oid, uid)
    if o["status"] != "PROPOSED":
        raise err(ERR_ORDER_INVALID_STATE, "order is not PROPOSED")
    o["status"] = "REJECTED"
    touch_common(o)
    return success(serialize(o))


@bp.post("/lending/acquisition-orders/<oid>/revise")
def revise_order(oid):
    body = require_body()
    model = opt_field(body, "model", (str,), enums=MODELS, default=None)
    copies = opt_field(body, "copies", (int,), default=None)
    prepaid = opt_field(body, "prepaid_balance_cents", (int,), default=None)
    role, uid = require_roles({"LibraryAdmin"})
    o = _own_order(oid, uid)
    if o["status"] != "REJECTED":
        raise err(ERR_ORDER_INVALID_STATE, "order is not REJECTED")
    new_model = model if model is not None else o["model"]
    new_copies = copies if copies is not None else (o["copies"] if model is None else None)
    if new_copies is None:
        new_copies = 1
    new_prepaid = prepaid if "prepaid_balance_cents" in body else (
        o["prepaid_balance_cents"] if model is None or model == "COST_PER_CIRC" else None)
    title = stores["titles"][o["title_id"]]
    _validate_terms(new_model, new_copies, new_prepaid, title)
    o["model"] = new_model
    o["copies"] = new_copies
    o["prepaid_balance_cents"] = new_prepaid
    o["estimated_cost_cents"] = _estimate(new_model, new_copies, new_prepaid, title)
    o["status"] = "DRAFT"
    touch_common(o)
    return success(serialize(o))


@bp.post("/lending/acquisition-orders/<oid>/cancel")
def cancel_order(oid):
    role, uid = require_roles({"LibraryAdmin"})
    o = _own_order(oid, uid)
    if o["status"] not in ("DRAFT", "PROPOSED", "APPROVED"):
        raise err(ERR_ORDER_INVALID_STATE, "order cannot be cancelled from its current state")
    was_approved = o["status"] == "APPROVED"
    o["status"] = "CANCELLED"
    touch_common(o)
    if was_approved:
        fund = stores["funds"][o["budget_fund_id"]]
        touch_common(fund)
        recompute_fund(fund)
    return success(serialize(o))


@bp.post("/lending/acquisition-orders/<oid>/fulfill")
def fulfill(oid):
    body = require_body()
    invoiced = req_field(body, "invoiced_cost_cents", (int,))
    role, uid = require_roles({"LibraryAdmin"})
    o = _own_order(oid, uid)
    if o["status"] != "APPROVED":
        raise err(ERR_ORDER_INVALID_STATE, "order is not APPROVED")
    fund = stores["funds"][o["budget_fund_id"]]
    if fund["status"] != "OPEN":
        raise err(ERR_FUND_CLOSED, "fund is not OPEN")
    fulfill_order(o, invoiced)
    return success(serialize(o))
