"""Master data: facilities, dough types, cafes, payments."""

from flask import Blueprint, request

import db
import response as resp
import services
import validators as V
from errors import ApiError
from middleware import (authorize, ALL_ROLES, ROLE_FACILITY_PLANNER,
                        ROLE_FINANCE_ADMIN)

bp = Blueprint("master", __name__)


# ---------------------------------------------------------------------------
# DoughFacility
# ---------------------------------------------------------------------------
@bp.route("/dough-ops/facilities", methods=["POST"])
def create_facility():
    authorize(ROLE_FACILITY_PLANNER)
    data = V.body_json(request)
    name = V.req_string(data, "name")
    capacity = V.req_int(data, "effective_capacity_units", minimum=1)
    row = db.common_fields()
    row.update({"name": name, "effective_capacity_units": capacity})
    db.facilities[row["id"]] = row
    return resp.object_response(resp.serialize(row), 201)


@bp.route("/dough-ops/facilities/<facility_id>", methods=["GET"])
def get_facility(facility_id):
    authorize(*ALL_ROLES)
    row = services.get_or_404(db.facilities, facility_id, "Facility")
    return resp.object_response(resp.serialize(row), 200)


# ---------------------------------------------------------------------------
# DoughType
# ---------------------------------------------------------------------------
@bp.route("/dough-ops/dough-types", methods=["POST"])
def create_dough_type():
    authorize(ROLE_FACILITY_PLANNER)
    data = V.body_json(request)
    code = V.req_string(data, "code")
    category = V.req_enum(data, "category", ("CONVENTIONAL", "ARTISAN"))
    shelf_life = V.req_int(data, "shelf_life_hours", minimum=1)
    cutoff = V.req_hhmm(data, "order_cutoff_local")
    substitution = V.req_bool(data, "substitution_allowed")
    price = V.req_number(data, "flat_transfer_price", minimum_exclusive=0)
    for existing in db.dough_types.values():
        if existing["code"] == code:
            raise ApiError("ERR_DUPLICATE", "A dough type with this code already exists.")
    row = db.common_fields()
    row.update({
        "code": code,
        "category": category,
        "shelf_life_hours": shelf_life,
        "order_cutoff_local": cutoff,
        "substitution_allowed": substitution,
        "flat_transfer_price": price,
    })
    db.dough_types[row["id"]] = row
    return resp.object_response(resp.serialize(row), 201)


@bp.route("/dough-ops/dough-types", methods=["GET"])
def list_dough_types():
    authorize(*ALL_ROLES)
    category = request.args.get("category")
    rows = [r for r in db.dough_types.values()
            if category is None or r["category"] == category]
    return resp.paginate(rows, resp.serialize)


@bp.route("/dough-ops/dough-types/<dough_type_id>", methods=["GET"])
def get_dough_type(dough_type_id):
    authorize(*ALL_ROLES)
    row = services.get_or_404(db.dough_types, dough_type_id, "Dough type")
    return resp.object_response(resp.serialize(row), 200)


# ---------------------------------------------------------------------------
# Cafe
# ---------------------------------------------------------------------------
@bp.route("/dough-ops/cafes", methods=["POST"])
def create_cafe():
    authorize(ROLE_FACILITY_PLANNER)
    data = V.body_json(request)
    name = V.req_string(data, "name")
    facility_id = data.get("facility_id")
    ownership = V.req_enum(data, "ownership_type", ("COMPANY", "FRANCHISE"))
    credit_limit = V.req_int(data, "credit_limit_cents", minimum=1)
    if not isinstance(facility_id, str) or facility_id not in db.facilities:
        raise ApiError("ERR_NOT_FOUND", "Facility not found.")
    row = db.common_fields()
    row.update({
        "name": name,
        "facility_id": facility_id,
        "ownership_type": ownership,
        "credit_limit_cents": credit_limit,
        "credit_balance_cents": 0,
    })
    db.cafes[row["id"]] = row
    return resp.object_response(resp.serialize(row), 201)


@bp.route("/dough-ops/cafes", methods=["GET"])
def list_cafes():
    authorize(*ALL_ROLES)
    facility_id = request.args.get("facility_id")
    ownership = request.args.get("ownership_type")
    rows = [r for r in db.cafes.values()
            if (facility_id is None or r["facility_id"] == facility_id)
            and (ownership is None or r["ownership_type"] == ownership)]
    return resp.paginate(rows, resp.serialize)


@bp.route("/dough-ops/cafes/<cafe_id>", methods=["GET"])
def get_cafe(cafe_id):
    authorize(*ALL_ROLES)
    row = services.get_or_404(db.cafes, cafe_id, "Cafe")
    return resp.object_response(resp.serialize(row), 200)


@bp.route("/dough-ops/cafes/<cafe_id>/payments", methods=["POST"])
def post_payment(cafe_id):
    authorize(ROLE_FINANCE_ADMIN)
    cafe = services.get_or_404(db.cafes, cafe_id, "Cafe")
    data = V.body_json(request)
    amount = V.req_int(data, "amount_cents", minimum=1)

    # Payment waterfall: INVOICED orders oldest-first (PRD 3.8).
    remaining = amount
    settled = []
    invoiced = [o for o in db.sorted_rows(db.cafe_orders)
                if o["cafe_id"] == cafe_id and o["billing_status"] == "INVOICED"]
    for order in invoiced:
        total = db.invoices.get(order["id"], 0)
        if remaining >= total:
            remaining -= total
            order["billing_status"] = "PAID"
            settled.append(order["id"])
            db.touch(order)
        else:
            break
    cafe["credit_balance_cents"] = max(0, cafe["credit_balance_cents"] - amount)
    db.touch(cafe)
    return resp.object_response({
        "applied_cents": amount - remaining,
        "settled_order_ids": settled,
        "credit_balance_cents": cafe["credit_balance_cents"],
    }, 201)
