"""Instrument custody: registration, booking, issue, return, quarantine, calibration."""
from decimal import Decimal

from flask import Blueprint

import calc
import clock
import db
import guards
import response
import services
from errors import ApiError

bp = Blueprint("equipment", __name__)

TYPES = ["ACOUSTIC_RECORDER", "GPS_LOGGER", "SPOTTING_SCOPE"]
CONDITIONS = ["GOOD", "DAMAGED", "LOST"]


def _page(rows, filters):
    rows = guards.apply_filters(rows, filters)
    page, limit, offset, total = guards.paginate(rows)
    return response.list_response([db.serialize(r) for r in page], limit, offset, total)


# --------------------------------------------------------------------------
# Equipment
# --------------------------------------------------------------------------
@bp.post("/citizen-science/equipment")
def create_equipment():
    guards.authenticate(["ProgramAdmin"])
    body = guards.validate_body([
        {"name": "asset_tag", "type": "string", "required": True},
        {"name": "equipment_type", "type": "enum", "required": True, "values": TYPES},
        {"name": "calibration_valid_until", "type": "datetime", "required": True},
    ])
    guards.require_unique(db.equipment, "asset_tag", body["asset_tag"])
    row = db.new_row({
        "asset_tag": body["asset_tag"],
        "equipment_type": body["equipment_type"],
        "status": "AVAILABLE",
        "calibration_valid_until": body["calibration_valid_until"],
        "calibration_drift_ppm": calc.rnd(Decimal("0.0"), 2),
        "quarantine_until": None,
        "total_loan_hours": 0,
    })
    db.equipment[row["id"]] = row
    return response.object_response(db.serialize(row), 201)


@bp.get("/citizen-science/equipment")
def list_equipment():
    actor = guards.authenticate(["ProgramAdmin", "Volunteer"])
    guards.resolve_actor(actor)
    return _page(db.all_rows(db.equipment), ["status", "equipment_type"])


@bp.get("/citizen-science/equipment/<pid>")
def read_equipment(pid):
    actor = guards.authenticate(["ProgramAdmin", "Volunteer"])
    row = guards.get_equipment(pid)
    guards.resolve_actor(actor)
    return response.object_response(db.serialize(row))


@bp.post("/citizen-science/equipment/<pid>/clear-quarantine")
def clear_quarantine(pid):
    guards.authenticate(["ProgramAdmin"])
    unit = guards.get_equipment(pid)
    if unit["status"] != "QUARANTINE":
        raise ApiError("ERR_EQUIPMENT_STATE_INVALID")
    if unit["quarantine_until"] is not None and clock.now() < unit["quarantine_until"]:
        raise ApiError("ERR_QUARANTINE_NOT_ELAPSED")

    drift = calc.dec(unit["calibration_drift_ppm"])
    unit["quarantine_until"] = None
    if drift < calc.CALIBRATION_DRIFT_LIMIT_PPM:
        unit["status"] = "AVAILABLE"
        db.touch(unit)
    elif drift < calc.CALIBRATION_RETIRE_PPM:
        unit["status"] = "IN_CALIBRATION"
        db.touch(unit)
    else:
        unit["status"] = "RETIRED"
        db.touch(unit)
        services.cancel_requested_loans(unit["id"])
    return response.object_response(db.serialize(unit))


@bp.post("/citizen-science/equipment/<pid>/complete-calibration")
def complete_calibration(pid):
    guards.authenticate(["ProgramAdmin"])
    unit = guards.get_equipment(pid)
    if unit["status"] != "IN_CALIBRATION":
        raise ApiError("ERR_EQUIPMENT_STATE_INVALID")
    unit["status"] = "AVAILABLE"
    unit["calibration_drift_ppm"] = calc.rnd(Decimal("0.0"), 2)
    unit["calibration_valid_until"] = clock.plus_days(clock.now(), calc.CALIBRATION_VALID_DAYS)
    db.touch(unit)
    return response.object_response(db.serialize(unit))


# --------------------------------------------------------------------------
# Equipment loans
# --------------------------------------------------------------------------
@bp.post("/citizen-science/equipment-loans")
def create_loan():
    actor = guards.authenticate(["ProgramAdmin", "Volunteer"])
    guards.resolve_actor(actor)
    body = guards.validate_body([
        {"name": "equipment_id", "type": "id", "required": True},
        {"name": "volunteer_id", "type": "id", "required": True},
        {"name": "start_at", "type": "datetime", "required": True},
        {"name": "due_at", "type": "datetime", "required": True},
        {"name": "expected_equipment_version", "type": "integer", "required": True},
    ])
    if body["due_at"] <= body["start_at"]:
        raise ApiError("ERR_INVALID_REQUEST")

    volunteer = guards.get_volunteer(body["volunteer_id"])
    unit = guards.get_equipment(body["equipment_id"])

    # priority 8 — ownership
    if actor["role"] == "Volunteer" and volunteer["id"] != actor["id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # priority 12 — optimistic concurrency
    if body["expected_equipment_version"] != unit["version"]:
        raise ApiError("ERR_STALE_EQUIPMENT_VERSION")

    # priority 24 — a retired unit may not be booked
    if unit["status"] == "RETIRED":
        raise ApiError("ERR_EQUIPMENT_STATE_INVALID")

    # priority 30 — volunteer standing
    if volunteer["status"] not in ("ACTIVE", "PROBATION"):
        raise ApiError("ERR_VOLUNTEER_NOT_IN_GOOD_STANDING")

    # priority 42 — half-open interval conflict
    if services.interval_conflicts(unit["id"], body["start_at"], body["due_at"]):
        raise ApiError("ERR_EQUIPMENT_INTERVAL_CONFLICT")

    row = db.new_row({
        "equipment_id": unit["id"],
        "volunteer_id": volunteer["id"],
        "start_at": body["start_at"],
        "due_at": body["due_at"],
        "issued_at": None,
        "returned_at": None,
        "status": "REQUESTED",
        "condition_on_return": "NONE",
        "loan_hours": 0,
        "drift_added_ppm": calc.rnd(Decimal("0.0"), 2),
    })
    db.loans[row["id"]] = row
    db.touch(unit)
    return response.object_response(db.serialize(row), 201)


@bp.get("/citizen-science/equipment-loans")
def list_loans():
    actor = guards.authenticate(["ProgramAdmin", "Volunteer"])
    guards.resolve_actor(actor)
    return _page(db.all_rows(db.loans), ["equipment_id", "volunteer_id", "status"])


@bp.get("/citizen-science/equipment-loans/<pid>")
def read_loan(pid):
    actor = guards.authenticate(["ProgramAdmin", "Volunteer"])
    row = guards.get_loan(pid)
    guards.resolve_actor(actor)
    return response.object_response(db.serialize(row))


@bp.post("/citizen-science/equipment-loans/<pid>/issue")
def issue_loan(pid):
    guards.authenticate(["ProgramAdmin"])
    loan = guards.get_loan(pid)
    if loan["status"] != "REQUESTED":
        raise ApiError("ERR_LOAN_STATE_INVALID")
    unit = db.equipment.get(loan["equipment_id"])
    if unit is None or unit["status"] != "AVAILABLE":
        raise ApiError("ERR_EQUIPMENT_STATE_INVALID")

    now = clock.now()
    if not unit["calibration_valid_until"] > now:
        raise ApiError("ERR_CALIBRATION_EXPIRED")
    if not now < loan["due_at"]:
        raise ApiError("ERR_LOAN_STATE_INVALID")

    loan["status"] = "ISSUED"
    loan["issued_at"] = now
    db.touch(loan)
    unit["status"] = "ON_LOAN"
    db.touch(unit)
    return response.object_response(db.serialize(loan))


@bp.post("/citizen-science/equipment-loans/<pid>/return")
def return_loan(pid):
    guards.authenticate(["ProgramAdmin"])
    loan = guards.get_loan(pid)
    body = guards.validate_body([
        {"name": "condition_on_return", "type": "enum", "required": True, "values": CONDITIONS},
    ])
    if loan["status"] not in ("ISSUED", "OVERDUE"):
        raise ApiError("ERR_LOAN_STATE_INVALID")

    was_overdue = loan["status"] == "OVERDUE"
    condition = body["condition_on_return"]
    now = clock.now()
    loan["returned_at"] = now
    loan["condition_on_return"] = condition
    issued_at = loan["issued_at"] if loan["issued_at"] is not None else now
    loan["loan_hours"] = calc.loan_hours_between(issued_at, now)
    loan["drift_added_ppm"] = calc.drift_for(loan["loan_hours"], condition, was_overdue)

    unit = db.equipment.get(loan["equipment_id"])

    if condition == "LOST":
        loan["status"] = "LOST"
        db.touch(loan)
        if unit is not None:
            unit["total_loan_hours"] += loan["loan_hours"]
            unit["status"] = "RETIRED"
            db.touch(unit)
            services.cancel_requested_loans(unit["id"])
    else:
        loan["status"] = "RETURNED"
        db.touch(loan)
        if unit is not None:
            unit["calibration_drift_ppm"] = calc.rnd(
                calc.dec(unit["calibration_drift_ppm"]) + calc.dec(loan["drift_added_ppm"]), 2)
            unit["total_loan_hours"] += loan["loan_hours"]
            unit["status"] = "QUARANTINE"
            unit["quarantine_until"] = clock.plus_hours(now, calc.QUARANTINE_HOURS)
            db.touch(unit)

    return response.object_response(db.serialize(loan))
