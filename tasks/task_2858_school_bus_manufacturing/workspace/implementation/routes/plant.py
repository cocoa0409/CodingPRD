"""Production lines, test bays and build slots (PRD 3.6)."""

from flask import Blueprint

import shapes
from db import (by_creation, date_plus, db, get_or_404, make_record, public,
                touch, values)
from errors import ApiError
from middleware import PLANT_SCHEDULER, actor
from response import created, list_response, object_response, q_enum, q_str
from services import calc, domain

bp = Blueprint("plant", __name__)

LINE_STATUSES = ("RUNNING", "DOWN_FOR_MAINTENANCE")
SLOT_STATUSES = ("PLANNED", "COMMITTED", "IN_PROGRESS", "COMPLETED", "RELEASED")


# --------------------------------------------------------- production lines

@bp.post("/production-lines")
def create_line():
    actor(PLANT_SCHEDULER)
    data = shapes.body()
    fields = {
        "line_code": shapes.get_str(data, "line_code"),
        "plant_code": shapes.get_str(data, "plant_code"),
        "supported_body_classes": shapes.get_str_array(
            data, "supported_body_classes", allowed=calc.BODY_CLASSES),
        "horizon_slot_day_capacity": shapes.get_int(
            data, "horizon_slot_day_capacity", minimum=1),
        "changeover_buffer_days": shapes.get_int(data, "changeover_buffer_days", minimum=0),
        "committed_slot_days": 0,
        "status": "RUNNING",
    }
    if domain.code_exists(db.lines, "line_code", fields["line_code"]):
        raise ApiError("ERR_DUPLICATE_CODE", "line_code is already registered.")
    line = make_record(fields)
    db.lines[line["id"]] = line
    return created(public(line))


@bp.get("/production-lines")
def list_lines():
    actor()
    plant_code = q_str("plant_code")
    status = q_enum("status", LINE_STATUSES)
    rows = []
    for line in values(db.lines):
        if plant_code is not None and line["plant_code"] != plant_code:
            continue
        if status is not None and line["status"] != status:
            continue
        rows.append(line)
    return list_response(by_creation(rows))


@bp.get("/production-lines/<line_id>")
def read_line(line_id):
    actor()
    line = get_or_404(db.lines, line_id, "ERR_PRODUCTION_LINE_NOT_FOUND")
    return object_response(public(line))


@bp.post("/production-lines/<line_id>/status")
def set_line_status(line_id):
    actor(PLANT_SCHEDULER)
    data = shapes.body()
    status = shapes.get_enum(data, "status", LINE_STATUSES)
    line = get_or_404(db.lines, line_id, "ERR_PRODUCTION_LINE_NOT_FOUND")
    line["status"] = status
    touch(line)
    return object_response(public(line))


# --------------------------------------------------------------- test bays

@bp.post("/test-bays")
def create_bay():
    actor(PLANT_SCHEDULER)
    data = shapes.body()
    fields = {
        "bay_code": shapes.get_str(data, "bay_code"),
        "plant_code": shapes.get_str(data, "plant_code"),
        "supported_test_types": shapes.get_str_array(
            data, "supported_test_types", allowed=calc.TEST_TYPES),
        "max_concurrent_electrical": shapes.get_int(
            data, "max_concurrent_electrical", minimum=1),
    }
    if domain.code_exists(db.bays, "bay_code", fields["bay_code"]):
        raise ApiError("ERR_DUPLICATE_CODE", "bay_code is already registered.")
    bay = make_record(fields)
    db.bays[bay["id"]] = bay
    return created(public(bay))


@bp.get("/test-bays")
def list_bays():
    actor()
    plant_code = q_str("plant_code")
    rows = [b for b in values(db.bays)
            if plant_code is None or b["plant_code"] == plant_code]
    return list_response(by_creation(rows))


@bp.get("/test-bays/<bay_id>")
def read_bay(bay_id):
    actor()
    bay = get_or_404(db.bays, bay_id, "ERR_TEST_BAY_NOT_FOUND")
    return object_response(public(bay))


# ------------------------------------------------------------- build slots

@bp.post("/build-slots")
def create_slot():
    actor(PLANT_SCHEDULER)
    data = shapes.body()
    expected_version = shapes.get_int(data, "expected_production_line_version", minimum=0)
    line_id = shapes.get_str(data, "production_line_id")
    unit_id = shapes.get_str(data, "bus_unit_id")
    start_raw, start_date = shapes.get_date(data, "start_date")
    end_raw, end_date = shapes.get_date(data, "end_date")

    line = get_or_404(db.lines, line_id, "ERR_PRODUCTION_LINE_NOT_FOUND")
    unit = get_or_404(db.units, unit_id, "ERR_BUS_UNIT_NOT_FOUND")

    if int(expected_version) != int(line["version"]):
        raise ApiError("ERR_STALE_LINE_VERSION")

    if not end_date > start_date:
        raise ApiError("ERR_INVALID_SLOT_WINDOW", "end_date must be strictly after start_date.")

    siblings = domain.slots_of_line(line["id"])
    for other in siblings:
        if other["status"] == "RELEASED":
            continue
        other_start = domain.to_date(other["start_date"])
        other_end = domain.to_date(other["end_date"])
        if start_date < other_end and other_start < end_date:
            raise ApiError("ERR_SLOT_WINDOW_OVERLAP")

    package = db.packages.get(unit["propulsion_package_id"])
    propulsion = package["propulsion_type"] if package else None

    preceding = None
    for other in siblings:
        if other["status"] not in ("PLANNED", "COMMITTED", "IN_PROGRESS", "COMPLETED"):
            continue
        other_end = domain.to_date(other["end_date"])
        if other_end > start_date:
            continue
        key = (other_end, other["created_at"], other["_seq"])
        if preceding is None or key > preceding[0]:
            preceding = (key, other)
    if preceding is not None and preceding[1]["propulsion_type"] != propulsion:
        gap = (start_date - domain.to_date(preceding[1]["end_date"])).days
        if gap < int(line["changeover_buffer_days"]):
            raise ApiError("ERR_CHANGEOVER_BUFFER_VIOLATION")

    order = domain.order_of_unit(unit)
    if order is not None:
        promised = domain.to_date(order["promised_delivery_date"])
        if date_plus(end_date, calc.FINISH_LEAD_DAYS) > promised:
            raise ApiError("ERR_SLOT_MISSES_DEADLINE")

    model = db.models.get(unit["bus_model_id"])
    if model is None or model["body_class"] not in line["supported_body_classes"]:
        raise ApiError("ERR_BODY_CLASS_UNSUPPORTED")

    slot = make_record({
        "production_line_id": line["id"],
        "bus_unit_id": unit["id"],
        "start_date": start_raw,
        "end_date": end_raw,
        "slot_days": (end_date - start_date).days,
        "propulsion_type": propulsion,
        "status": "PLANNED",
    })
    db.slots[slot["id"]] = slot
    touch(line)
    return created(public(slot))


@bp.get("/build-slots")
def list_slots():
    actor()
    line_id = q_str("production_line_id")
    unit_id = q_str("bus_unit_id")
    status = q_enum("status", SLOT_STATUSES)
    propulsion = q_enum("propulsion_type", calc.PROPULSION_TYPES)
    rows = []
    for slot in values(db.slots):
        if line_id is not None and slot["production_line_id"] != line_id:
            continue
        if unit_id is not None and slot["bus_unit_id"] != unit_id:
            continue
        if status is not None and slot["status"] != status:
            continue
        if propulsion is not None and slot["propulsion_type"] != propulsion:
            continue
        rows.append(slot)
    return list_response(by_creation(rows))


@bp.get("/build-slots/<slot_id>")
def read_slot(slot_id):
    actor()
    slot = get_or_404(db.slots, slot_id, "ERR_BUILD_SLOT_NOT_FOUND")
    return object_response(public(slot))


@bp.post("/build-slots/<slot_id>/commit")
def commit_slot(slot_id):
    actor(PLANT_SCHEDULER)
    slot = get_or_404(db.slots, slot_id, "ERR_BUILD_SLOT_NOT_FOUND")
    unit = db.units.get(slot["bus_unit_id"])
    line = db.lines.get(slot["production_line_id"])
    if unit is None or unit["production_status"] != "PLANNED":
        raise ApiError("ERR_UNIT_PHASE_INVALID")
    if slot["status"] != "PLANNED":
        raise ApiError("ERR_SLOT_STATE_INVALID")
    if line is None or line["status"] != "RUNNING":
        raise ApiError("ERR_LINE_DOWN_FOR_MAINTENANCE")
    if int(line["committed_slot_days"]) + int(slot["slot_days"]) > int(
            line["horizon_slot_day_capacity"]):
        raise ApiError("ERR_LINE_CAPACITY_EXCEEDED")

    slot["status"] = "COMMITTED"
    touch(slot)
    domain.recompute_line_ledger(line)
    touch(line)
    unit["production_status"] = "SLOTTED"
    touch(unit)
    domain.recompute_order(domain.order_of_unit(unit))
    return object_response(public(slot))


@bp.post("/build-slots/<slot_id>/release")
def release_slot_endpoint(slot_id):
    actor(PLANT_SCHEDULER)
    slot = get_or_404(db.slots, slot_id, "ERR_BUILD_SLOT_NOT_FOUND")
    if slot["status"] not in ("PLANNED", "COMMITTED", "IN_PROGRESS"):
        raise ApiError("ERR_SLOT_STATE_INVALID")
    domain.release_slot(slot)
    return object_response(public(slot))
