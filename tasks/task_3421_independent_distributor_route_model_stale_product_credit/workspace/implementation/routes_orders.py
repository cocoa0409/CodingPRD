"""Daily order routes: create/list, submit, confirm, cancel, delivery, reconcile."""
from flask import Blueprint, request

import auth
import calc
import clock
import domain
import store
import validators as V
from constants import (
    ROLE_COMPANY_ADMIN, ROLE_ROUTE_OPS, ROLE_CREDIT_ANALYST, ROLE_DISTRIBUTOR,
    ORDER_LEAD_DAYS,
)
from errors import (
    ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_AGREEMENT_NOT_ACTIVE, ERR_PRODUCTION_DAY_LOCKED, ERR_CAPACITY_EXCEEDED,
    ERR_STALE_VERSION, ERR_ORDER_LEAD_TIME, ERR_SKU_UNKNOWN,
    ERR_CREDIT_LIMIT_EXCEEDED, raise_err,
)
from response import ok_object, ok_list, pagination_params, body

bp = Blueprint("orders", __name__)

ALL = (ROLE_COMPANY_ADMIN, ROLE_ROUTE_OPS, ROLE_CREDIT_ANALYST, ROLE_DISTRIBUTOR)
DIST = (ROLE_DISTRIBUTOR,)
OPS = (ROLE_ROUTE_OPS,)


def load_order(rid, user_id=None, role=None):
    order = store.get("orders", rid)
    if order is None:
        raise_err(ERR_NOT_FOUND, "Order not found")
    if user_id is not None:
        auth.check_resource_owner(user_id, role, order["distributor_id"])
    return order


def parse_line_pairs(raw_lines, field, allow_zero_qty=False):
    """Validate a [{sku, qty}] array; returns a normalized list."""
    if not isinstance(raw_lines, list) or not raw_lines:
        raise_err(ERR_INVALID_REQUEST, f"Field {field} must be a non-empty array")
    normalized = []
    seen = set()
    minimum = 0 if allow_zero_qty else 1
    for line in raw_lines:
        if not isinstance(line, dict):
            raise_err(ERR_INVALID_REQUEST, f"{field} entries must be objects")
        sku = V.get_str(line, "sku")
        qty = V.get_int(line, "qty", minimum=minimum)
        if sku in seen:
            raise_err(ERR_INVALID_REQUEST, f"Duplicate sku in {field}: {sku}")
        seen.add(sku)
        normalized.append({"sku": sku, "qty": qty})
    return normalized


def require_active_agreement(order):
    agreement = domain.resolve_agreement(
        order["distributor_id"], for_date=order["_delivery_date"], active_only=True)
    if agreement is None:
        raise_err(ERR_AGREEMENT_NOT_ACTIVE,
                  "The distributor must hold an ACTIVE agreement")
    return agreement


@bp.route("/distributors/<rid>/orders", methods=["POST"])
def create_order(rid):
    user_id, role = auth.caller()
    auth.require_role(role, DIST)
    auth.require_path_distributor(user_id, role, rid)
    if store.get("distributors", rid) is None:
        raise_err(ERR_NOT_FOUND, "Distributor not found")
    data = body()
    date_str, date_obj = V.get_date(data, "delivery_date")
    if "lines" not in data or data["lines"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: lines")
    lines = parse_line_pairs(data["lines"], "lines")
    agreement = domain.resolve_agreement(rid, for_date=date_obj)
    catalog = domain.catalog_of(agreement)
    for line in lines:
        if line["sku"] not in catalog:
            raise_err(ERR_SKU_UNKNOWN,
                      f"sku {line['sku']} is not in the agreement bakery catalog")
    order = store.insert("orders", {
        "distributor_id": rid,
        "delivery_date": date_str,
        "lines": lines,
        "units_total": sum(l["qty"] for l in lines),
        "status": "DRAFT",
        "submitted_on": None,
        "delivered_lines": None,
        "total_charge_cents": None,
        "verified_lines": None,
        "shortage_credit_cents": 0,
        "cancelled_reason": None,
        "_agreement_id": agreement["id"] if agreement else None,
        "_delivery_date": date_obj,
        "_delivered_date": None,
    })
    return ok_object(order, 201)


@bp.route("/distributors/<rid>/orders", methods=["GET"])
def list_orders(rid):
    user_id, role = auth.caller()
    auth.require_role(role, ALL)
    auth.require_path_distributor(user_id, role, rid)
    if store.get("distributors", rid) is None:
        raise_err(ERR_NOT_FOUND, "Distributor not found")
    orders = domain.orders_of(rid)
    status = request.args.get("status")
    if status is not None:
        orders = [o for o in orders if o["status"] == status]
    date_filter = request.args.get("delivery_date")
    if date_filter is not None:
        orders = [o for o in orders if o["delivery_date"] == date_filter]
    page = pagination_params()
    total = len(orders)
    window = orders[page["offset"]:page["offset"] + page["limit"]]
    return ok_list(window, total, page)


@bp.route("/orders/<rid>/submit", methods=["POST"])
def submit_order(rid):
    user_id, role = auth.caller()
    auth.require_role(role, DIST)
    order = load_order(rid, user_id, role)
    if order["status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Only a DRAFT order can be submitted")
    agreement = require_active_agreement(order)
    catalog = domain.catalog_of(agreement)
    for line in order["lines"]:
        if line["sku"] not in catalog:
            raise_err(ERR_SKU_UNKNOWN,
                      f"sku {line['sku']} is not in the agreement bakery catalog")
    if (order["_delivery_date"] - clock.today()).days < ORDER_LEAD_DAYS:
        raise_err(ERR_ORDER_LEAD_TIME,
                  "delivery_date must fall at least 2 days after the current date")
    order["status"] = "SUBMITTED"
    order["submitted_on"] = clock.iso()
    order["_agreement_id"] = agreement["id"]
    store.touch(order)
    return ok_object(order)


@bp.route("/orders/<rid>/confirm", methods=["POST"])
def confirm_order(rid):
    user_id, role = auth.caller()
    auth.require_role(role, OPS)
    order = load_order(rid)
    data = body()
    expected_version = V.get_int(data, "expected_production_day_version")
    if order["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Only a SUBMITTED order can be confirmed")
    agreement = require_active_agreement(order)
    day = domain.find_production_day(agreement["bakery_id"], order["delivery_date"])
    if day is None:
        raise_err(ERR_NOT_FOUND, "No production day exists for this bakery and date")
    if day["status"] != "PLANNING":
        raise_err(ERR_PRODUCTION_DAY_LOCKED, "The production day is closed")
    if expected_version != day["version"]:
        raise_err(ERR_STALE_VERSION,
                  "expected_production_day_version does not match the day version")
    if day["allocated_units"] + order["units_total"] > day["capacity_units"]:
        raise_err(ERR_CAPACITY_EXCEEDED,
                  "Confirm would exceed the production day capacity")
    order["status"] = "CONFIRMED"
    order["_agreement_id"] = agreement["id"]
    store.touch(order)
    day["allocated_units"] += order["units_total"]
    store.touch(day)
    return ok_object(order)


@bp.route("/orders/<rid>/cancel", methods=["POST"])
def cancel_order(rid):
    user_id, role = auth.caller()
    auth.require_role(role, DIST)
    order = load_order(rid, user_id, role)
    if order["status"] not in ("SUBMITTED", "CONFIRMED"):
        raise_err(ERR_INVALID_STATE,
                  "Only a SUBMITTED or CONFIRMED order can be cancelled")
    was_confirmed = order["status"] == "CONFIRMED"
    order["status"] = "CANCELLED"
    order["cancelled_reason"] = "DISTRIBUTOR_CANCELLED"
    store.touch(order)
    if was_confirmed:
        domain.release_reservation(order)
    return ok_object(order)


@bp.route("/orders/<rid>/record-delivery", methods=["POST"])
def record_delivery(rid):
    user_id, role = auth.caller()
    auth.require_role(role, DIST)
    order = load_order(rid, user_id, role)
    data = body()
    if "delivered_lines" not in data or data["delivered_lines"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: delivered_lines")
    delivered = parse_line_pairs(data.get("delivered_lines"), "delivered_lines",
                                 allow_zero_qty=True)
    if {l["sku"] for l in delivered} != {l["sku"] for l in order["lines"]}:
        raise_err(ERR_INVALID_REQUEST,
                  "delivered_lines must cover exactly the order's line skus")
    if order["status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE, "Only a CONFIRMED order can record delivery")
    agreement = require_active_agreement(order)
    day = domain.find_production_day(agreement["bakery_id"], order["delivery_date"])
    if day is None:
        raise_err(ERR_NOT_FOUND, "No production day exists for this bakery and date")
    if day["status"] != "CLOSED":
        raise_err(ERR_PRODUCTION_DAY_LOCKED,
                  "The production day is not yet closed")
    catalog = domain.catalog_of(agreement)
    charge = calc.order_charge(delivered, catalog, agreement["discount_pct"])
    distributor = store.get("distributors", order["distributor_id"])
    if distributor["trade_balance_cents"] + charge > distributor["credit_limit_cents"]:
        raise_err(ERR_CREDIT_LIMIT_EXCEEDED,
                  "Recording delivery would exceed the distributor credit limit")
    order["status"] = "DELIVERED"
    order["delivered_lines"] = delivered
    order["total_charge_cents"] = charge
    order["_delivered_date"] = clock.today()
    store.touch(order)
    distributor["trade_balance_cents"] += charge
    store.touch(distributor)
    domain.recompute_standing(distributor)
    return ok_object(order)


@bp.route("/orders/<rid>/reconcile", methods=["POST"])
def reconcile_order(rid):
    user_id, role = auth.caller()
    auth.require_role(role, OPS)
    order = load_order(rid)
    data = body()
    if "verified_lines" not in data or data["verified_lines"] is None:
        raise_err(ERR_INVALID_REQUEST, "Missing required field: verified_lines")
    verified = parse_line_pairs(data.get("verified_lines"), "verified_lines",
                                allow_zero_qty=True)
    delivered_map = {l["sku"]: l["qty"] for l in order["delivered_lines"] or []}
    if {l["sku"] for l in verified} != set(delivered_map):
        raise_err(ERR_INVALID_REQUEST,
                  "verified_lines must cover exactly the delivered skus")
    for line in verified:
        if line["qty"] > delivered_map[line["sku"]]:
            raise_err(ERR_INVALID_REQUEST,
                      "verified qty may not exceed the delivered qty")
    if order["status"] != "DELIVERED":
        raise_err(ERR_INVALID_STATE, "Only a DELIVERED order can be reconciled")
    agreement = store.get("agreements", order.get("_agreement_id") or "")
    catalog = domain.catalog_of(agreement)
    verified_map = {l["sku"]: l["qty"] for l in verified}
    shortage = calc.shortage_credit(order["delivered_lines"], verified_map,
                                    catalog, agreement["discount_pct"])
    order["status"] = "RECONCILED"
    order["verified_lines"] = verified
    order["shortage_credit_cents"] = shortage
    store.touch(order)
    distributor = store.get("distributors", order["distributor_id"])
    distributor["trade_balance_cents"] -= shortage
    store.touch(distributor)
    domain.recompute_standing(distributor)
    return ok_object(order)
