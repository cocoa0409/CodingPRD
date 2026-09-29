"""PRD 3.1 — telecom rooms, grounding verification and energizing."""

from flask import Blueprint, request

import calc
import lookup
import rollups
import serial
from auth import (CERTIFIER, CLIENT, DESIGN_ENGINEER, INSTALLER, PROJECT_MANAGER,
                  TEST_TECHNICIAN, require)
from envelope import created, enum_filter, ok, paginate
from errors import ApiError
from store import D, base_record, db, touch
from validation import Field, body, no_body

rooms_bp = Blueprint("rooms", __name__)

ROOM_CODE_PATTERN = r"^[A-Z]{2}[0-9]{2}$"
ROOM_STATES = ("ROUGH_IN", "GROUNDED", "ENERGIZED")
GROUNDING_STATUSES = ("UNVERIFIED", "COMPLIANT", "NON_COMPLIANT")

READ_ROLES = (PROJECT_MANAGER, DESIGN_ENGINEER, INSTALLER, TEST_TECHNICIAN,
              CERTIFIER, CLIENT)


@rooms_bp.route("/cabling/telecom-rooms", methods=["POST"])
@require(PROJECT_MANAGER)
def add_room():
    values = body([
        Field("project_id", "string"),
        Field("room_code", "string", pattern=ROOM_CODE_PATTERN),
        Field("floor", "integer"),
        Field("branch_circuit_amps", "integer", minimum=15),
        Field("ups_capacity_va", "integer", minimum=0),
    ])
    project = lookup.project(values["project_id"])
    for existing in db.rooms.values():
        if (existing["project_id"] == project["id"]
                and existing["room_code"] == values["room_code"]):
            raise ApiError("ERR_INVALID_REQUEST",
                           "room_code must be unique among the rooms of the project.")
    room = base_record()
    room.update({
        "project_id": project["id"],
        "room_code": values["room_code"],
        "floor": values["floor"],
        "branch_circuit_amps": values["branch_circuit_amps"],
        "ups_capacity_va": values["ups_capacity_va"],
        "room_state": "ROUGH_IN",
        "tgb_installed": False,
        "bonding_conductor_awg": None,
        "ground_resistance_milliohms": None,
        "grounding_status": "UNVERIFIED",
        "power_load_va": 0,
        "power_headroom_va": values["ups_capacity_va"],
    })
    db.rooms[room["id"]] = room
    return created(serial.public(room))


@rooms_bp.route("/cabling/telecom-rooms/<room_id>", methods=["GET"])
@require(*READ_ROLES)
def read_room(room_id):
    return ok(serial.public(lookup.room(room_id)))


@rooms_bp.route("/cabling/telecom-rooms", methods=["GET"])
@require(*READ_ROLES)
def list_rooms():
    project_id = request.args.get("project_id")
    room_state = enum_filter(request.args, "room_state", ROOM_STATES)
    grounding_status = enum_filter(request.args, "grounding_status", GROUNDING_STATUSES)
    rows = []
    for room in db.rooms.values():
        if project_id is not None and room["project_id"] != project_id:
            continue
        if room_state is not None and room["room_state"] != room_state:
            continue
        if grounding_status is not None and room["grounding_status"] != grounding_status:
            continue
        rows.append(room)
    return paginate(rows, request.args, serial.public)


@rooms_bp.route("/cabling/telecom-rooms/<room_id>/grounding-verification",
                methods=["POST"])
@require(PROJECT_MANAGER, CERTIFIER)
def verify_grounding(room_id):
    values = body([
        Field("tgb_installed", "bool"),
        Field("bonding_conductor_awg", "integer"),
        Field("ground_resistance_milliohms", "number"),
    ])
    room = lookup.room(room_id)
    if room["room_state"] == "ENERGIZED":
        raise ApiError("ERR_INVALID_ROOM_STATE",
                       "An energized room accepts no further grounding verification.")
    if values["bonding_conductor_awg"] > calc.BONDING_MAX_AWG:
        raise ApiError("ERR_BONDING_NON_COMPLIANT",
                       "A bonding conductor thinner than #6 AWG is a code violation.")
    # Each verification overwrites the previously recorded measurements.
    room["tgb_installed"] = values["tgb_installed"]
    room["bonding_conductor_awg"] = values["bonding_conductor_awg"]
    room["ground_resistance_milliohms"] = values["ground_resistance_milliohms"]
    compliant = (values["tgb_installed"] is True
                 and values["bonding_conductor_awg"] <= calc.BONDING_MAX_AWG
                 and D(values["ground_resistance_milliohms"])
                 <= calc.GROUND_RESISTANCE_MAX_MILLIOHMS)
    if compliant:
        room["grounding_status"] = "COMPLIANT"
        room["room_state"] = "GROUNDED"
    else:
        room["grounding_status"] = "NON_COMPLIANT"
        room["room_state"] = "ROUGH_IN"
    touch(room)
    return ok(serial.public(room))


@rooms_bp.route("/cabling/telecom-rooms/<room_id>/energize", methods=["POST"])
@require(PROJECT_MANAGER)
def energize_room(room_id):
    no_body()
    room = lookup.room(room_id)
    if room["room_state"] == "ENERGIZED":
        raise ApiError("ERR_INVALID_ROOM_STATE", "The room is already energized.")
    if room["grounding_status"] != "COMPLIANT":
        raise ApiError("ERR_ROOM_NOT_GROUNDED",
                       "The room must be graded COMPLIANT before it is energized.")
    released = [c for c in rollups.project_coordinations(room["project_id"])
                if c["trade"] == "ELECTRICAL" and c["milestone"] == "POWER_ENERGIZE"
                and c["coordination_state"] == "RELEASED"]
    if not released:
        raise ApiError("ERR_TRADE_NOT_COORDINATED",
                       "A RELEASED ELECTRICAL / POWER_ENERGIZE coordination is required.")
    if room["power_load_va"] > room["ups_capacity_va"]:
        raise ApiError("ERR_POWER_CAPACITY_EXCEEDED",
                       "power_load_va exceeds the room's ups_capacity_va.")
    room["room_state"] = "ENERGIZED"
    touch(room)
    return ok(serial.public(room))
