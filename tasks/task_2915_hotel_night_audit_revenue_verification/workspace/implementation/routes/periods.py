"""Accounting periods and the month-end tie-out."""
from flask import Blueprint

import db
import response
import shapes
from constants import PREFIX
from errors import ApiError
from middleware import ALL_ROLES, CONTROLLER, authenticate
from money import ZERO
from services import calc, derive, lookup, serial

bp = Blueprint("periods", __name__, url_prefix=PREFIX)


@bp.route("/accounting-periods/<row_id>/tie-out", methods=["POST"])
def tie_out(row_id):
    user_id, _role = authenticate([CONTROLLER])
    body = shapes.parse([
        shapes.Field("gl_control_total_amount", "number", required=True),
    ])
    period = lookup.get_period(row_id)
    if period["status"] not in ("OPEN", "TIE_OUT_FAILED"):
        raise ApiError("ERR_PERIOD_NOT_TIEABLE",
                       "The period is not in a tieable state.")
    if int(period["tie_out_attempt_count"]) >= 3:
        raise ApiError("ERR_TIE_OUT_ATTEMPT_LIMIT_REACHED",
                       "The period has exhausted its tie-out attempts.")
    days = derive.dates_of_period(period["id"])
    for day in days:
        if day["status"] not in ("CLOSED", "ARCHIVED"):
            raise ApiError("ERR_PERIOD_HAS_OPEN_DATES",
                           "Every operating day must be closed or archived.")

    period["gl_control_total_amount"] = body["gl_control_total_amount"]
    subsystem = derive.period_subsystem_total(period)
    variance = derive.q2(body["gl_control_total_amount"] - subsystem)
    if variance == ZERO:
        period["status"] = "TIED_OUT"
        period["tied_out_at"] = db.now()
        period["tied_out_by_user_id"] = user_id
        period["audit_trail_retention_until_date"] = calc.retention_until(
            period["period_month"]
        )
        for day in days:
            if day["status"] == "CLOSED":
                day["status"] = "ARCHIVED"
                derive.touch(day)
    else:
        period["status"] = "TIE_OUT_FAILED"
        period["tie_out_attempt_count"] = int(period["tie_out_attempt_count"]) + 1
    derive.touch(period)
    return response.ok(serial.period_out(period))


@bp.route("/accounting-periods/<row_id>", methods=["GET"])
def get_period(row_id):
    authenticate(ALL_ROLES)
    return response.ok(serial.period_out(lookup.get_period(row_id)))


@bp.route("/accounting-periods", methods=["GET"])
def list_periods():
    authenticate(ALL_ROLES)
    rows = db.all_of("periods")
    property_id = shapes.q("property_id")
    period_month = shapes.q("period_month")
    status = shapes.q("status")
    if property_id is not None:
        rows = [r for r in rows if r["property_id"] == property_id]
    if period_month is not None:
        rows = [r for r in rows if r["period_month"] == period_month]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    items, meta = shapes.page(rows, serial.period_out)
    return response.collection(items, meta)
