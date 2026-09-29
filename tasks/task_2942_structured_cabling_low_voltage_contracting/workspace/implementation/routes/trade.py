"""PRD 3.6 — coordinating the other trades, with an acyclic predecessor chain."""

from flask import Blueprint, request

import lookup
import serial
from auth import (CERTIFIER, CLIENT, DESIGN_ENGINEER, INSTALLER, PROJECT_MANAGER,
                  require)
from envelope import created, enum_filter, ok, paginate
from errors import ApiError
from store import base_record, db, touch
from validation import Field, body, no_body

trade_bp = Blueprint("trade", __name__)

TRADES = ("CEILING", "ELECTRICAL", "MECHANICAL", "FIRE_ALARM")
MILESTONES = ("PATHWAY_ROUGH_IN", "CEILING_CLOSE", "POWER_ENERGIZE", "DUCT_CLOSE")
COORDINATION_STATES = ("REQUESTED", "CONFIRMED", "RELEASED", "BLOCKED")
MAX_CHAIN_HOPS = 8
READ_ROLES = (PROJECT_MANAGER, DESIGN_ENGINEER, INSTALLER, CERTIFIER, CLIENT)


def _predecessor_chain(coordination):
    """Coordinations visited walking upwards from (and including) this one."""
    chain = []
    cursor = coordination
    while cursor is not None:
        if any(c["id"] == cursor["id"] for c in chain):
            break
        chain.append(cursor)
        parent_id = cursor.get("predecessor_coordination_id")
        cursor = db.coordinations.get(parent_id) if parent_id else None
    return chain


@trade_bp.route("/cabling/trade-coordinations", methods=["POST"])
@require(PROJECT_MANAGER)
def request_coordination():
    values = body([
        Field("project_id", "string"),
        Field("trade", "enum", enum=TRADES),
        Field("milestone", "enum", enum=MILESTONES),
        Field("predecessor_coordination_id", "string", required=False, default=None,
              nullable=True),
    ])
    project = lookup.project(values["project_id"])
    predecessor = lookup.coordination(values["predecessor_coordination_id"])
    if predecessor is not None:
        if predecessor["project_id"] != project["id"]:
            raise ApiError("ERR_CROSS_PROJECT_REFERENCE",
                           "predecessor_coordination_id belongs to a different project.")
        chain = _predecessor_chain(predecessor)
        for member in chain:
            if (member["trade"] == values["trade"]
                    and member["milestone"] == values["milestone"]):
                raise ApiError("ERR_COORDINATION_CYCLE",
                               "A milestone may not depend on itself, however indirectly.")
        if len(chain) > MAX_CHAIN_HOPS:
            raise ApiError("ERR_COORDINATION_CYCLE",
                           "The predecessor chain is longer than 8 hops.")
    coordination = base_record()
    coordination.update({
        "project_id": project["id"],
        "trade": values["trade"],
        "milestone": values["milestone"],
        "predecessor_coordination_id":
            predecessor["id"] if predecessor is not None else None,
        "confirmed_date": None,
        "coordination_state": "REQUESTED",
        "block_reason": None,
    })
    db.coordinations[coordination["id"]] = coordination
    return created(serial.public(coordination))


@trade_bp.route("/cabling/trade-coordinations/<coordination_id>", methods=["GET"])
@require(*READ_ROLES)
def read_coordination(coordination_id):
    return ok(serial.public(lookup.coordination(coordination_id)))


@trade_bp.route("/cabling/trade-coordinations", methods=["GET"])
@require(*READ_ROLES)
def list_coordinations():
    project_id = request.args.get("project_id")
    predecessor_coordination_id = request.args.get("predecessor_coordination_id")
    trade = enum_filter(request.args, "trade", TRADES)
    milestone = enum_filter(request.args, "milestone", MILESTONES)
    coordination_state = enum_filter(request.args, "coordination_state",
                                     COORDINATION_STATES)
    rows = []
    for coordination in db.coordinations.values():
        if project_id is not None and coordination["project_id"] != project_id:
            continue
        if (predecessor_coordination_id is not None
                and coordination["predecessor_coordination_id"]
                != predecessor_coordination_id):
            continue
        if trade is not None and coordination["trade"] != trade:
            continue
        if milestone is not None and coordination["milestone"] != milestone:
            continue
        if (coordination_state is not None
                and coordination["coordination_state"] != coordination_state):
            continue
        rows.append(coordination)
    return paginate(rows, request.args, serial.public)


@trade_bp.route("/cabling/trade-coordinations/<coordination_id>/confirm",
                methods=["POST"])
@require(PROJECT_MANAGER)
def confirm_coordination(coordination_id):
    values = body([Field("confirmed_date", "date")])
    coordination = lookup.coordination(coordination_id)
    if coordination["coordination_state"] != "REQUESTED":
        raise ApiError("ERR_INVALID_COORDINATION_STATE",
                       "Only a REQUESTED coordination can be confirmed.")
    predecessor_id = coordination["predecessor_coordination_id"]
    if predecessor_id:
        predecessor = db.coordinations.get(predecessor_id)
        if predecessor is None or predecessor["coordination_state"] != "RELEASED":
            raise ApiError("ERR_PREDECESSOR_NOT_RELEASED",
                           "The predecessor coordination has not been released yet.")
    coordination["coordination_state"] = "CONFIRMED"
    coordination["confirmed_date"] = values["confirmed_date"]
    touch(coordination)
    return ok(serial.public(coordination))


@trade_bp.route("/cabling/trade-coordinations/<coordination_id>/release",
                methods=["POST"])
@require(PROJECT_MANAGER)
def release_coordination(coordination_id):
    no_body()
    coordination = lookup.coordination(coordination_id)
    if coordination["coordination_state"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_COORDINATION_STATE",
                       "Only a CONFIRMED coordination can be released.")
    coordination["coordination_state"] = "RELEASED"
    touch(coordination)
    return ok(serial.public(coordination))


@trade_bp.route("/cabling/trade-coordinations/<coordination_id>/block", methods=["POST"])
@require(PROJECT_MANAGER)
def block_coordination(coordination_id):
    values = body([Field("block_reason", "string")])
    coordination = lookup.coordination(coordination_id)
    if coordination["coordination_state"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_COORDINATION_STATE",
                       "Only a CONFIRMED coordination can be blocked.")
    coordination["coordination_state"] = "BLOCKED"
    coordination["block_reason"] = values["block_reason"]
    touch(coordination)
    return ok(serial.public(coordination))


@trade_bp.route("/cabling/trade-coordinations/<coordination_id>/unblock",
                methods=["POST"])
@require(PROJECT_MANAGER)
def unblock_coordination(coordination_id):
    no_body()
    coordination = lookup.coordination(coordination_id)
    if coordination["coordination_state"] != "BLOCKED":
        raise ApiError("ERR_INVALID_COORDINATION_STATE",
                       "Only a BLOCKED coordination can be unblocked.")
    coordination["coordination_state"] = "REQUESTED"
    coordination["block_reason"] = None
    coordination["confirmed_date"] = None
    touch(coordination)
    return ok(serial.public(coordination))
