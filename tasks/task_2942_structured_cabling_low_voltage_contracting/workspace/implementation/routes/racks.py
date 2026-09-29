"""PRD 3.2 — racks, the rack-unit elevation and the room power ledger."""

from flask import Blueprint, request

import calc
import lookup
import rollups
import serial
from auth import (CERTIFIER, CLIENT, DESIGN_ENGINEER, INSTALLER, PROJECT_MANAGER,
                  TEST_TECHNICIAN, require)
from envelope import created, enum_filter, ok, paginate
from errors import ApiError
from store import base_record, db, touch
from validation import Field, body

racks_bp = Blueprint("racks", __name__)

RACK_CODE_PATTERN = r"^[A-Z]$"
ASSIGNMENT_STATES = ("ACTIVE", "RELEASED")

RACK_READ_ROLES = (PROJECT_MANAGER, DESIGN_ENGINEER, INSTALLER, TEST_TECHNICIAN,
                   CERTIFIER, CLIENT)
ASSIGNMENT_READ_ROLES = (PROJECT_MANAGER, DESIGN_ENGINEER, INSTALLER, CERTIFIER)


@racks_bp.route("/cabling/racks", methods=["POST"])
@require(DESIGN_ENGINEER)
def add_rack():
    values = body([
        Field("telecom_room_id", "string"),
        Field("rack_code", "string", pattern=RACK_CODE_PATTERN),
        Field("total_ru", "integer", minimum=1, maximum=52),
    ])
    room = lookup.room(values["telecom_room_id"])
    for existing in db.racks.values():
        if (existing["telecom_room_id"] == room["id"]
                and existing["rack_code"] == values["rack_code"]):
            raise ApiError("ERR_INVALID_REQUEST",
                           "rack_code must be unique among the racks of the room.")
    rack = base_record()
    rack.update({
        "telecom_room_id": room["id"],
        "rack_code": values["rack_code"],
        "total_ru": values["total_ru"],
        "occupied_ru": 0,
        "available_ru": values["total_ru"],
        "power_draw_va": 0,
    })
    db.racks[rack["id"]] = rack
    return created(serial.public(rack))


@racks_bp.route("/cabling/racks/<rack_id>", methods=["GET"])
@require(*RACK_READ_ROLES)
def read_rack(rack_id):
    return ok(serial.public(lookup.rack(rack_id)))


@racks_bp.route("/cabling/racks", methods=["GET"])
@require(*RACK_READ_ROLES)
def list_racks():
    telecom_room_id = request.args.get("telecom_room_id")
    rows = [r for r in db.racks.values()
            if telecom_room_id is None or r["telecom_room_id"] == telecom_room_id]
    return paginate(rows, request.args, serial.public)


@racks_bp.route("/cabling/rack-unit-assignments", methods=["POST"])
@require(DESIGN_ENGINEER)
def place_equipment():
    values = body([
        Field("rack_id", "string"),
        Field("equipment_label", "string"),
        Field("start_ru", "integer", minimum=1),
        Field("end_ru", "integer", minimum=1),
        Field("power_va", "integer", minimum=0),
        Field("expected_rack_version", "integer"),
    ])
    if values["start_ru"] > values["end_ru"]:
        raise ApiError("ERR_INVALID_REQUEST", "start_ru must be no greater than end_ru.")
    rack = lookup.rack(values["rack_id"])
    room = db.rooms.get(rack["telecom_room_id"])
    if values["expected_rack_version"] != rack["version"]:
        raise ApiError("ERR_STALE_RACK_VERSION",
                       "expected_rack_version does not match the rack's current version.")
    for existing in rollups.by_field(db.assignments, "rack_id", rack["id"]):
        if existing["assignment_state"] != "ACTIVE":
            continue
        if calc.ru_intervals_conflict(values["start_ru"], values["end_ru"],
                                      existing["start_ru"], existing["end_ru"]):
            raise ApiError("ERR_RACK_RU_CONFLICT",
                           "The rack-unit interval overlaps an active placement.")
    if values["end_ru"] > rack["total_ru"]:
        raise ApiError("ERR_RACK_CAPACITY_EXCEEDED",
                       "end_ru is beyond the rack's total_ru.")
    if room is not None:
        if room["power_load_va"] + values["power_va"] > room["ups_capacity_va"]:
            raise ApiError("ERR_POWER_CAPACITY_EXCEEDED",
                           "The placement would push the room past its ups_capacity_va.")

    assignment = base_record()
    assignment.update({
        "rack_id": rack["id"],
        "equipment_label": values["equipment_label"],
        "start_ru": values["start_ru"],
        "end_ru": values["end_ru"],
        "span_ru": calc.span_ru(values["start_ru"], values["end_ru"]),
        "power_va": values["power_va"],
        "assignment_state": "ACTIVE",
        "released_reason": None,
    })
    db.assignments[assignment["id"]] = assignment
    # hop 2 — the rack ledger, caused by the placement
    rollups.recompute_rack_ledger(rack)
    touch(rack)
    # hop 3 — the room ledger, caused by the rack ledger
    if room is not None:
        rollups.recompute_room_power(room)
        touch(room)
    return created(serial.public(assignment))


@racks_bp.route("/cabling/rack-unit-assignments/<assignment_id>", methods=["GET"])
@require(*ASSIGNMENT_READ_ROLES)
def read_assignment(assignment_id):
    return ok(serial.public(lookup.assignment(assignment_id)))


@racks_bp.route("/cabling/rack-unit-assignments", methods=["GET"])
@require(*ASSIGNMENT_READ_ROLES)
def list_assignments():
    rack_id = request.args.get("rack_id")
    assignment_state = enum_filter(request.args, "assignment_state", ASSIGNMENT_STATES)
    rows = []
    for assignment in db.assignments.values():
        if rack_id is not None and assignment["rack_id"] != rack_id:
            continue
        if (assignment_state is not None
                and assignment["assignment_state"] != assignment_state):
            continue
        rows.append(assignment)
    return paginate(rows, request.args, serial.public)


@racks_bp.route("/cabling/rack-unit-assignments/<assignment_id>/release",
                methods=["POST"])
@require(DESIGN_ENGINEER)
def release_assignment(assignment_id):
    values = body([
        Field("released_reason", "string"),
        Field("expected_rack_version", "integer"),
    ])
    assignment = lookup.assignment(assignment_id)
    rack = db.racks.get(assignment["rack_id"])
    if assignment["assignment_state"] != "ACTIVE":
        raise ApiError("ERR_INVALID_ASSIGNMENT_STATE",
                       "Only an ACTIVE placement can be released.")
    if rack is not None and values["expected_rack_version"] != rack["version"]:
        raise ApiError("ERR_STALE_RACK_VERSION",
                       "expected_rack_version does not match the rack's current version.")
    assignment["assignment_state"] = "RELEASED"
    assignment["released_reason"] = values["released_reason"]
    touch(assignment)
    if rack is not None:
        rollups.recompute_rack_ledger(rack)
        touch(rack)
        room = db.rooms.get(rack["telecom_room_id"])
        if room is not None:
            rollups.recompute_room_power(room)
            touch(room)
    return ok(serial.public(assignment))
