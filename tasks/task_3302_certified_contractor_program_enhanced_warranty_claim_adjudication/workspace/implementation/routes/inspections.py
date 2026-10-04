"""Inspection order routes."""
from flask import Blueprint

from db import db
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_INSPECTOR_CAPACITY_EXCEEDED,
    ERR_OWNERSHIP_MISMATCH, not_found,
)
from middleware import require_roles
from response import success
from services.helpers import (
    body_json, require_fields, require_string, parse_date, touch,
)

bp = Blueprint("inspections", __name__)


def _get_order(oid):
    o = db.inspection_orders.get(oid)
    if o is None:
        raise not_found("InspectionOrder")
    return o


@bp.post("/program/inspection-orders/<oid>/schedule")
def schedule_order(oid):
    require_roles("ProgramAdmin")
    data = body_json()
    require_fields(data, ["inspector_id", "service_date"])
    inspector_id = require_string(data, "inspector_id")
    service_date = require_string(data, "service_date")
    parse_date(service_date)
    with db.lock:
        order = _get_order(oid)
        if order["status"] != "REQUESTED":
            raise ApiError(ERR_INVALID_STATE, 409, "Inspection order is not REQUESTED")
        count = sum(
            1 for o in db.inspection_orders.values()
            if o["inspector_id"] == inspector_id
            and o["service_date"] == service_date
            and o["status"] == "SCHEDULED"
        )
        if count >= 3:
            raise ApiError(ERR_INSPECTOR_CAPACITY_EXCEEDED, 422,
                           "Inspector capacity exceeded for that date")
        order["inspector_id"] = inspector_id
        order["service_date"] = service_date
        order["status"] = "SCHEDULED"
        touch(order)
    return success(order)


@bp.post("/program/inspection-orders/<oid>/complete")
def complete_order(oid):
    user_id, role = require_roles("Inspector")
    data = body_json()
    require_fields(data, ["findings", "confirms_defect"])
    findings = data["findings"]
    if not isinstance(findings, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "findings must be a string")
    confirms = data["confirms_defect"]
    if not isinstance(confirms, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "confirms_defect must be a boolean")
    with db.lock:
        order = _get_order(oid)
        if order.get("inspector_id") is not None and order["inspector_id"] != user_id:
            raise ApiError(ERR_OWNERSHIP_MISMATCH, 403,
                           "Only the assigned inspector may complete this order")
        if order["status"] != "SCHEDULED":
            raise ApiError(ERR_INVALID_STATE, 409, "Inspection order is not SCHEDULED")
        order["findings"] = findings
        order["confirms_defect"] = confirms
        order["status"] = "COMPLETED"
        touch(order)
        # claim auto-advance
        claim = db.claims.get(order["claim_id"])
        if claim is not None and claim["status"] == "INSPECTION_REQUESTED":
            outstanding = any(
                o["claim_id"] == claim["id"] and o["status"] in ("REQUESTED", "SCHEDULED")
                for o in db.inspection_orders.values()
            )
            if not outstanding:
                claim["status"] = "INSPECTION_COMPLETED"
                touch(claim)
    return success(order)
