"""Cafe orders (PRD 3.2) with the parallel billing axis (PRD 3.8)."""

from flask import Blueprint, request

import db
import response as resp
import services
import validators as V
from errors import ApiError
from middleware import (authorize, require_cafe_owner, ALL_ROLES,
                        ROLE_CAFE_MANAGER)

bp = Blueprint("orders", __name__)


def _occ_check(cafe, expected):
    """Priority 15: optimistic concurrency against the cafe aggregate."""
    if expected is None:
        raise ApiError("ERR_VALIDATION", "Field 'expected_cafe_version' is required.")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_VALIDATION", "Field 'expected_cafe_version' must be an integer.")
    if expected != cafe["version"]:
        raise ApiError("ERR_STALE_VERSION", "The supplied cafe version is stale.")


@bp.route("/dough-ops/cafe-orders", methods=["POST"])
def create_cafe_order():
    authorize(ROLE_CAFE_MANAGER)
    data = V.body_json(request)
    cafe_id = data.get("cafe_id")
    dough_type_id = data.get("dough_type_id")
    production_date = V.req_date(data, "production_date")
    quantity = V.req_int(data, "quantity", minimum=1)
    expected = data.get("expected_cafe_version")

    if not isinstance(cafe_id, str) or cafe_id not in db.cafes:
        raise ApiError("ERR_NOT_FOUND", "Cafe not found.")
    require_cafe_owner(cafe_id)
    if not isinstance(dough_type_id, str) or dough_type_id not in db.dough_types:
        raise ApiError("ERR_NOT_FOUND", "Dough type not found.")
    cafe = db.cafes[cafe_id]
    _occ_check(cafe, expected)

    row = db.common_fields()
    row.update({
        "cafe_id": cafe_id,
        "dough_type_id": dough_type_id,
        "production_date": production_date,
        "quantity": quantity,
        "adjusted_quantity": services.compute_adjusted_quantity(
            quantity, cafe_id, production_date),
        "status": "DRAFT",
        "billing_status": "UNBILLED",
        "actual_quantity": None,
        "_plan_id": None,
    })
    db.cafe_orders[row["id"]] = row
    db.touch(cafe)
    return resp.object_response(resp.serialize(row), 201)


@bp.route("/dough-ops/cafe-orders", methods=["GET"])
def list_cafe_orders():
    authorize(*ALL_ROLES)
    cafe_id = request.args.get("cafe_id")
    dough_type_id = request.args.get("dough_type_id")
    production_date = request.args.get("production_date")
    status = request.args.get("status")
    billing_status = request.args.get("billing_status")
    rows = [r for r in db.cafe_orders.values()
            if (cafe_id is None or r["cafe_id"] == cafe_id)
            and (dough_type_id is None or r["dough_type_id"] == dough_type_id)
            and (production_date is None or r["production_date"] == production_date)
            and (status is None or r["status"] == status)
            and (billing_status is None or r["billing_status"] == billing_status)]
    return resp.paginate(rows, resp.serialize)


@bp.route("/dough-ops/cafe-orders/<order_id>", methods=["GET"])
def get_cafe_order(order_id):
    authorize(*ALL_ROLES)
    services.sweep_autolock()
    row = services.get_or_404(db.cafe_orders, order_id, "Order")
    return resp.object_response(resp.serialize(row), 200)


@bp.route("/dough-ops/cafe-orders/<order_id>/submit", methods=["POST"])
def submit_cafe_order(order_id):
    authorize(ROLE_CAFE_MANAGER)
    order = services.get_or_404(db.cafe_orders, order_id, "Order")
    require_cafe_owner(order["cafe_id"])
    # Priority 5: state gate.
    if order["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT order may be submitted.")
    cafe = db.cafes[order["cafe_id"]]
    dough_type = db.dough_types[order["dough_type_id"]]
    # Priority 7: order cutoff.
    if services.cutoff_passed(dough_type, order["production_date"]):
        raise ApiError("ERR_ORDER_CUTOFF_PASSED", "The order cutoff has passed.")
    # Priority 11: credit limit (provisional invoice on requested quantity).
    provisional = services.provisional_invoice_cents(dough_type, cafe, order["quantity"])
    if cafe["credit_balance_cents"] + provisional > cafe["credit_limit_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", "The cafe's credit limit would be exceeded.")
    order["status"] = "SUBMITTED"
    db.touch(order)
    db.touch(cafe)
    return resp.object_response(resp.serialize(order), 200)


@bp.route("/dough-ops/cafe-orders/<order_id>/amend", methods=["POST"])
def amend_cafe_order(order_id):
    authorize(ROLE_CAFE_MANAGER)
    order = services.get_or_404(db.cafe_orders, order_id, "Order")
    require_cafe_owner(order["cafe_id"])
    # Priority 5/6: state + locked guard.
    if order["status"] == "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a SUBMITTED order may be amended.")
    if order["status"] != "SUBMITTED":
        raise ApiError("ERR_ORDER_LOCKED", "The order is locked; amendment is no longer allowed.")
    dough_type = db.dough_types[order["dough_type_id"]]
    # Priority 7: order cutoff.
    if services.cutoff_passed(dough_type, order["production_date"]):
        raise ApiError("ERR_ORDER_CUTOFF_PASSED", "The order cutoff has passed.")
    data = V.body_json(request)
    quantity = V.req_int(data, "quantity", minimum=1)
    cafe = db.cafes[order["cafe_id"]]
    # Priority 15: OCC.
    _occ_check(cafe, data.get("expected_cafe_version"))

    order["quantity"] = quantity
    order["adjusted_quantity"] = services.compute_adjusted_quantity(
        quantity, order["cafe_id"], order["production_date"])
    order["status"] = "DRAFT"
    db.touch(order)
    db.touch(cafe)
    return resp.object_response(resp.serialize(order), 200)


@bp.route("/dough-ops/cafe-orders/<order_id>/cancel", methods=["POST"])
def cancel_cafe_order(order_id):
    authorize(ROLE_CAFE_MANAGER)
    order = services.get_or_404(db.cafe_orders, order_id, "Order")
    require_cafe_owner(order["cafe_id"])
    # Priority 6: locked guard.
    if order["status"] not in ("DRAFT", "SUBMITTED"):
        if order["status"] == "CANCELLED":
            raise ApiError("ERR_INVALID_STATE", "The order is already cancelled.")
        raise ApiError("ERR_ORDER_LOCKED", "The order is locked; cancellation is no longer allowed.")
    cafe = db.cafes[order["cafe_id"]]
    order["status"] = "CANCELLED"
    db.touch(order)
    db.touch(cafe)
    return resp.object_response(resp.serialize(order), 200)
