"""Price override requests and manager decisions (PRD 3.6)."""

from flask import Blueprint

from constants import (ROLE_TECHNICIAN, ROLE_DISPATCHER, ROLE_MANAGER)
from common import (body_json, require_roles, require_str, require_int,
                    optional_str, enum_field, require_field)
import store
import serializers
import calc
from errors import (ApiError, not_found, invalid_request,
                    ERR_OVERRIDE_ALREADY_PENDING, ERR_STALE_VERSION,
                    ERR_OVERRIDE_EXCEEDS_LIMIT, ERR_INVALID_STATE)
from response import created, object_ok, array_ok, read_pagination, paginate
from flask import request

bp = Blueprint("overrides", __name__)

DECISION_APPROVE = {"APPROVE", "APPROVED"}
DECISION_REJECT = {"REJECT", "REJECTED"}


def _get_appointment(appointment_id):
    row = store.appointments.get(appointment_id)
    if row is None:
        raise not_found("appointment")
    return row


@bp.route("/appointments/<appointment_id>/override-requests", methods=["POST"])
def file_override(appointment_id):
    require_roles([ROLE_TECHNICIAN])
    appointment = _get_appointment(appointment_id)
    payload = body_json()
    requested = require_int(payload, "requested_price_cents")
    if requested <= 0:
        raise invalid_request("requested_price_cents must be strictly greater than zero")

    # state legality (priority 4): SCHEDULED or DISPATCHED only
    if appointment["status"] not in ("SCHEDULED", "DISPATCHED"):
        raise ApiError(ERR_INVALID_STATE)

    # already-pending override guard (priority 6)
    for existing in store.override_requests.values():
        if existing["appointment_id"] == appointment_id and existing["status"] == "PENDING":
            raise ApiError(ERR_OVERRIDE_ALREADY_PENDING)

    labor_base = calc.appointment_labor_base(appointment_id)
    row = store.new_row(
        "PricebookOverrideRequest",
        appointment_id=appointment_id,
        original_quote_cents=appointment["quoted_price_cents"],
        requested_price_cents=requested,
        max_approved_price_cents=calc.max_approved_price(labor_base),
        status="PENDING",
        decided_by_user_id=None,
    )
    store.override_requests[row["id"]] = row
    appointment["pricing_status"] = "OVERRIDE_PENDING"
    store.touch(appointment)
    return created(serializers.override_request(row))


@bp.route("/appointments/<appointment_id>/override-requests", methods=["GET"])
def list_overrides(appointment_id):
    require_roles([ROLE_DISPATCHER, ROLE_TECHNICIAN, ROLE_MANAGER])
    _get_appointment(appointment_id)
    limit, offset = read_pagination(request.args)
    items = [r for r in store.by_created(store.override_requests)
             if r["appointment_id"] == appointment_id]
    page, total = paginate(items, limit, offset)
    return array_ok([serializers.override_request(r) for r in page], limit, offset, total)


@bp.route("/override-requests/<request_id>/decide", methods=["POST"])
def decide_override(request_id):
    role, user_id = require_roles([ROLE_MANAGER])
    row = store.override_requests.get(request_id)
    if row is None:
        raise not_found("price override request")
    payload = body_json()
    decision = require_str(payload, "decision").strip().upper()
    if decision not in DECISION_APPROVE and decision not in DECISION_REJECT:
        raise invalid_request("decision must be APPROVE or REJECT")
    expected = require_field(payload, "expected_appointment_version")
    if isinstance(expected, bool) or not isinstance(expected, (int, float)):
        raise invalid_request("expected_appointment_version must be an integer")

    appointment = _get_appointment(row["appointment_id"])

    # PRD 2.10: "the override-decision stale-version check (`ERR_STALE_VERSION`, HTTP
    # 412) is evaluated whenever a decision is attempted against an appointment that
    # has since advanced ... enforced as a precondition of their own operation rather
    # than as a rank in the business-guard sequence", so it is tested ahead of the
    # decision's own state legality (priority 4).
    if int(appointment["version"]) != int(expected):
        raise ApiError(ERR_STALE_VERSION)
    if appointment["quoted_price_cents"] != row["original_quote_cents"]:
        raise ApiError(ERR_STALE_VERSION)

    # state legality (priority 4)
    if row["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE)

    if decision in DECISION_APPROVE:
        # override price ceiling (priority 16)
        if row["requested_price_cents"] > row["max_approved_price_cents"]:
            raise ApiError(ERR_OVERRIDE_EXCEEDS_LIMIT)
        row["status"] = "APPROVED"
        row["decided_by_user_id"] = user_id
        store.touch(row)
        appointment["quoted_price_cents"] = row["requested_price_cents"]
        appointment["pricing_status"] = "QUOTE_APPROVED"
        appointment["authorization_required"] = calc.authorization_required_for(
            appointment["quoted_price_cents"],
            calc.appointment_labor_base(appointment["id"]))
        store.touch(appointment)
        return object_ok(serializers.override_request(row))

    row["status"] = "REJECTED"
    row["decided_by_user_id"] = user_id
    store.touch(row)
    appointment["pricing_status"] = "QUOTE_REJECTED"
    store.touch(appointment)

    technician_id = appointment.get("technician_id")
    technician = store.technicians.get(technician_id) if technician_id else None
    if technician is not None:
        technician["sales_coaching_strike_count"] = int(
            technician["sales_coaching_strike_count"]) + 1
        strikes = int(technician["sales_coaching_strike_count"])
        if strikes >= 3:
            technician["performance_status"] = "PROBATION"
        elif strikes >= 2:
            technician["performance_status"] = "COACHING"
        store.touch(technician)

    return object_ok(serializers.override_request(row))