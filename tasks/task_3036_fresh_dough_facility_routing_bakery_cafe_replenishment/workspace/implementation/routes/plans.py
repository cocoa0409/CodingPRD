"""Production plans (PRD 3.4): sweep, capacity gate, release, close/invoicing."""

from flask import Blueprint, request

import db
import response as resp
import services
import validators as V
from errors import ApiError
from middleware import authorize, ALL_ROLES, ROLE_FACILITY_PLANNER

bp = Blueprint("plans", __name__)


@bp.route("/dough-ops/facilities/<facility_id>/production-plans", methods=["POST"])
def create_production_plan(facility_id):
    authorize(ROLE_FACILITY_PLANNER)
    facility = services.get_or_404(db.facilities, facility_id, "Facility")
    data = V.body_json(request)
    production_date = V.req_date(data, "production_date")

    for plan in db.production_plans.values():
        if plan["facility_id"] == facility_id and plan["production_date"] == production_date:
            raise ApiError("ERR_DUPLICATE",
                           "A production plan already exists for this facility and date.")

    services.sweep_autolock()

    row = db.common_fields()
    row.update({
        "facility_id": facility_id,
        "production_date": production_date,
        "status": "OPEN",
        "total_effective_units": 0,
        "over_capacity": False,
    })
    db.production_plans[row["id"]] = row

    # Sweep every LOCKED order for this facility and date into the plan.
    for order in db.sorted_rows(db.cafe_orders):
        if order["status"] != "LOCKED" or order["production_date"] != production_date:
            continue
        cafe = db.cafes.get(order["cafe_id"])
        if cafe is None or cafe["facility_id"] != facility_id:
            continue
        order["status"] = "PLANNED"
        order["_plan_id"] = row["id"]
        db.touch(order)
    services.recompute_plan_totals(row)
    db.touch(facility)
    return resp.object_response(resp.serialize(row), 201)


def _list_plans(rows):
    return resp.paginate(rows, resp.serialize)


@bp.route("/dough-ops/facilities/<facility_id>/production-plans", methods=["GET"])
def list_production_plans(facility_id):
    authorize(*ALL_ROLES)
    services.get_or_404(db.facilities, facility_id, "Facility")
    production_date = request.args.get("production_date")
    status = request.args.get("status")
    rows = [r for r in db.production_plans.values()
            if r["facility_id"] == facility_id
            and (production_date is None or r["production_date"] == production_date)
            and (status is None or r["status"] == status)]
    return _list_plans(rows)


@bp.route("/dough-ops/production-plans", methods=["GET"])
def list_production_plans_flat():
    authorize(*ALL_ROLES)
    facility_id = request.args.get("facility_id")
    production_date = request.args.get("production_date")
    status = request.args.get("status")
    rows = [r for r in db.production_plans.values()
            if (facility_id is None or r["facility_id"] == facility_id)
            and (production_date is None or r["production_date"] == production_date)
            and (status is None or r["status"] == status)]
    return _list_plans(rows)


@bp.route("/dough-ops/production-plans/<plan_id>", methods=["GET"])
def get_production_plan(plan_id):
    authorize(*ALL_ROLES)
    row = services.get_or_404(db.production_plans, plan_id, "Production plan")
    return resp.object_response(resp.serialize(row), 200)


@bp.route("/dough-ops/facilities/<facility_id>/production-plans/<plan_id>/lock",
          methods=["POST"])
def lock_production_plan(facility_id, plan_id):
    authorize(ROLE_FACILITY_PLANNER)
    facility = services.get_or_404(db.facilities, facility_id, "Facility")
    plan = services.get_or_404(db.production_plans, plan_id, "Production plan")
    if plan["facility_id"] != facility_id:
        raise ApiError("ERR_NOT_FOUND", "Production plan not found under this facility.")
    if plan["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN plan may be locked.")
    # Priority 12: capacity hard gate (inclusive at the limit).
    if plan["total_effective_units"] > facility["effective_capacity_units"]:
        raise ApiError("ERR_CAPACITY_EXCEEDED", "The plan exceeds facility capacity.")
    plan["status"] = "LOCKED"
    db.touch(plan)
    db.touch(facility)
    return resp.object_response(resp.serialize(plan), 200)


@bp.route("/dough-ops/facilities/<facility_id>/production-plans/<plan_id>/release",
          methods=["POST"])
def release_production_plan(facility_id, plan_id):
    authorize(ROLE_FACILITY_PLANNER)
    facility = services.get_or_404(db.facilities, facility_id, "Facility")
    plan = services.get_or_404(db.production_plans, plan_id, "Production plan")
    if plan["facility_id"] != facility_id:
        raise ApiError("ERR_NOT_FOUND", "Production plan not found under this facility.")
    if plan["status"] != "LOCKED":
        raise ApiError("ERR_INVALID_STATE", "Only a LOCKED plan may be released.")
    if plan["over_capacity"]:
        raise ApiError("ERR_CAPACITY_EXCEEDED", "An over-capacity plan cannot be released.")
    data = V.body_json(request)
    expected = data.get("expected_facility_version")
    if expected is None:
        raise ApiError("ERR_VALIDATION", "Field 'expected_facility_version' is required.")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise ApiError("ERR_VALIDATION", "Field 'expected_facility_version' must be an integer.")
    if expected != facility["version"]:
        raise ApiError("ERR_STALE_VERSION", "The supplied facility version is stale.")

    plan["status"] = "RELEASED"
    db.touch(plan)
    for order in services.plan_orders(plan):
        if order["status"] == "PLANNED":
            order["status"] = "ROUTED"
            db.touch(order)
    db.touch(facility)
    return resp.object_response(resp.serialize(plan), 200)


@bp.route("/dough-ops/facilities/<facility_id>/production-plans/<plan_id>/close",
          methods=["POST"])
def close_production_plan(facility_id, plan_id):
    authorize(ROLE_FACILITY_PLANNER)
    facility = services.get_or_404(db.facilities, facility_id, "Facility")
    plan = services.get_or_404(db.production_plans, plan_id, "Production plan")
    if plan["facility_id"] != facility_id:
        raise ApiError("ERR_NOT_FOUND", "Production plan not found under this facility.")
    if plan["status"] != "RELEASED":
        raise ApiError("ERR_INVALID_STATE", "Only a RELEASED plan may be closed.")
    orders = services.plan_orders(plan)
    if any(o["status"] not in services.TERMINAL_ORDER_STATES for o in orders):
        raise ApiError("ERR_INVALID_STATE",
                       "Every attached order must be terminal before the plan closes.")

    # Invoice each delivered/shipped-short order (PRD 3.8); the zero-invoice
    # CREDITED orders (route-cancel cascade) are left untouched.
    for order in orders:
        if order["status"] not in ("DELIVERED", "SHIPPED_SHORT"):
            continue
        dough_type = db.dough_types[order["dough_type_id"]]
        cafe = db.cafes[order["cafe_id"]]
        total = services.final_invoice_cents(dough_type, cafe, order["actual_quantity"] or 0)
        db.invoices[order["id"]] = total
        order["billing_status"] = "INVOICED"
        db.touch(order)
        cafe["credit_balance_cents"] += total
        db.touch(cafe)
    plan["status"] = "CLOSED"
    db.touch(plan)
    db.touch(facility)
    return resp.object_response(resp.serialize(plan), 200)
