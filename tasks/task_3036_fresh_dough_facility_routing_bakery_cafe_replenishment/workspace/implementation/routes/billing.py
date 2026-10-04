"""Billing periods and settlement lines (PRD 3.10)."""

import math
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

import db
import response as resp
import services
import validators as V
from errors import ApiError
from middleware import authorize, ALL_ROLES, ROLE_FINANCE_ADMIN

bp = Blueprint("billing", __name__)


@bp.route("/dough-ops/facilities/<facility_id>/billing-periods", methods=["POST"])
def create_billing_period(facility_id):
    authorize(ROLE_FINANCE_ADMIN)
    services.get_or_404(db.facilities, facility_id, "Facility")
    data = V.body_json(request)
    period_start = V.req_date(data, "period_start")
    period_end = V.req_date(data, "period_end")
    admin_pool_cents = V.req_int(data, "admin_pool_cents", minimum=0)
    row = db.common_fields()
    row.update({
        "facility_id": facility_id,
        "period_start": period_start,
        "period_end": period_end,
        "status": "OPEN",
        "admin_pool_cents": admin_pool_cents,
        "total_cafe_hours": 0,
    })
    db.billing_periods[row["id"]] = row
    return resp.object_response(resp.serialize(row), 201)


@bp.route("/dough-ops/facilities/<facility_id>/billing-periods", methods=["GET"])
def list_billing_periods(facility_id):
    authorize(*ALL_ROLES)
    services.get_or_404(db.facilities, facility_id, "Facility")
    status = request.args.get("status")
    rows = [r for r in db.billing_periods.values()
            if r["facility_id"] == facility_id
            and (status is None or r["status"] == status)]
    return resp.paginate(rows, resp.serialize)


@bp.route("/dough-ops/billing-periods", methods=["GET"])
def list_billing_periods_flat():
    authorize(*ALL_ROLES)
    facility_id = request.args.get("facility_id")
    status = request.args.get("status")
    rows = [r for r in db.billing_periods.values()
            if (facility_id is None or r["facility_id"] == facility_id)
            and (status is None or r["status"] == status)]
    return resp.paginate(rows, resp.serialize)


@bp.route("/dough-ops/billing-periods/<period_id>", methods=["GET"])
def get_billing_period(period_id):
    authorize(*ALL_ROLES)
    row = services.get_or_404(db.billing_periods, period_id, "Billing period")
    return resp.object_response(resp.serialize(row), 200)


def _get_period_under_facility(facility_id, period_id):
    services.get_or_404(db.facilities, facility_id, "Facility")
    period = services.get_or_404(db.billing_periods, period_id, "Billing period")
    if period["facility_id"] != facility_id:
        raise ApiError("ERR_NOT_FOUND", "Billing period not found under this facility.")
    return period


@bp.route("/dough-ops/facilities/<facility_id>/billing-periods/<period_id>/settlement-lines",
          methods=["POST"])
def create_settlement_line(facility_id, period_id):
    authorize(ROLE_FINANCE_ADMIN)
    period = _get_period_under_facility(facility_id, period_id)
    data = V.body_json(request)
    cafe_id = data.get("cafe_id")
    cafe_hours = V.req_int(data, "cafe_hours", minimum=0)
    if not isinstance(cafe_id, str) or cafe_id not in db.cafes:
        raise ApiError("ERR_NOT_FOUND", "Cafe not found.")
    if period["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE",
                       "Settlement lines may only be added while the period is OPEN.")

    row = db.common_fields()
    row.update({
        "billing_period_id": period_id,
        "cafe_id": cafe_id,
        "cafe_hours": cafe_hours,
        "direct_invoice_cents": 0,
        "allocated_indirect_cents": 0,
        "burden_share": None,
        "allocated_amount_cents": 0,
        "unit_allocated_cost": None,
        "cafe_total_units": 0,
    })
    db.settlement_lines[row["id"]] = row
    return resp.object_response(resp.serialize(row), 201)


@bp.route("/dough-ops/facilities/<facility_id>/billing-periods/<period_id>/settlement-lines",
          methods=["GET"])
def list_settlement_lines(facility_id, period_id):
    authorize(*ALL_ROLES)
    _get_period_under_facility(facility_id, period_id)
    cafe_id = request.args.get("cafe_id")
    rows = [r for r in db.settlement_lines.values()
            if r["billing_period_id"] == period_id
            and (cafe_id is None or r["cafe_id"] == cafe_id)]
    return resp.paginate(rows, resp.serialize)


@bp.route("/dough-ops/settlement-lines", methods=["GET"])
def list_settlement_lines_flat():
    authorize(*ALL_ROLES)
    period_id = request.args.get("billing_period_id")
    cafe_id = request.args.get("cafe_id")
    rows = [r for r in db.settlement_lines.values()
            if (period_id is None or r["billing_period_id"] == period_id)
            and (cafe_id is None or r["cafe_id"] == cafe_id)]
    return resp.paginate(rows, resp.serialize)


@bp.route("/dough-ops/settlement-lines/<line_id>", methods=["GET"])
def get_settlement_line(line_id):
    authorize(*ALL_ROLES)
    row = services.get_or_404(db.settlement_lines, line_id, "Settlement line")
    return resp.object_response(resp.serialize(row), 200)


def _cafe_period_figures(cafe, period):
    """Direct invoice cents and delivered units for one cafe inside the period."""
    direct = 0
    all_units = 0
    artisan_units = 0
    for order in db.cafe_orders.values():
        if order["cafe_id"] != cafe["id"]:
            continue
        if not (period["period_start"] <= order["production_date"] <= period["period_end"]):
            continue
        if order["billing_status"] in ("INVOICED", "PAID", "CREDITED"):
            direct += db.invoices.get(order["id"], 0)
        if order["status"] in ("DELIVERED", "SHIPPED_SHORT"):
            actual = order["actual_quantity"] or 0
            all_units += actual
            dough_type = db.dough_types.get(order["dough_type_id"])
            if dough_type and dough_type["category"] == "ARTISAN":
                artisan_units += actual
    if cafe["ownership_type"] == "FRANCHISE":
        total_units = all_units
    else:
        total_units = artisan_units
    return direct, total_units


@bp.route("/dough-ops/facilities/<facility_id>/billing-periods/<period_id>/close",
          methods=["POST"])
def close_billing_period(facility_id, period_id):
    authorize(ROLE_FINANCE_ADMIN)
    period = _get_period_under_facility(facility_id, period_id)
    if period["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Only an OPEN period may be closed.")
    lines = [r for r in db.sorted_rows(db.settlement_lines)
             if r["billing_period_id"] == period_id]
    if not lines:
        raise ApiError("ERR_INVALID_STATE",
                       "At least one settlement line must exist before close.")

    # Pass 1: total hours across every line, zero-hour cafes included. Fixed
    # before any per-line figure is derived.
    total_hours = sum(l["cafe_hours"] for l in lines)

    # Pass 2: per-line allocation.
    pool = Decimal(period["admin_pool_cents"])
    for line in lines:
        cafe = db.cafes[line["cafe_id"]]
        if total_hours > 0:
            share = (pool * Decimal(line["cafe_hours"]) / Decimal(total_hours)).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP)
        else:
            share = Decimal(0)
        allocated_indirect = int(share)
        burden = (services.FRANCHISE_BURDEN_SHARE if cafe["ownership_type"] == "FRANCHISE"
                  else services.COMPANY_BURDEN_SHARE)
        allocated_amount = math.floor(Decimal(allocated_indirect) * burden)
        direct, total_units = _cafe_period_figures(cafe, period)
        if total_units > 0:
            unit_cost = (Decimal(direct + allocated_amount) / Decimal(total_units)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP)
            unit_cost = float(unit_cost)
        else:
            unit_cost = None

        line["direct_invoice_cents"] = direct
        line["allocated_indirect_cents"] = allocated_indirect
        line["burden_share"] = float(burden)
        line["allocated_amount_cents"] = allocated_amount
        line["unit_allocated_cost"] = unit_cost
        line["cafe_total_units"] = total_units
        db.touch(line)

    period["total_cafe_hours"] = total_hours
    period["status"] = "CLOSED"
    db.touch(period)
    return resp.object_response(resp.serialize(period), 200)


@bp.route("/dough-ops/facilities/<facility_id>/billing-periods/<period_id>/settle",
          methods=["POST"])
def settle_billing_period(facility_id, period_id):
    authorize(ROLE_FINANCE_ADMIN)
    period = _get_period_under_facility(facility_id, period_id)
    if period["status"] != "CLOSED":
        raise ApiError("ERR_INVALID_STATE", "Only a CLOSED period may be settled.")
    period["status"] = "SETTLED"
    db.touch(period)
    return resp.object_response(resp.serialize(period), 200)
