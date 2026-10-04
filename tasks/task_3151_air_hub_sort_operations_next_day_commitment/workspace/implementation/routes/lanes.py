"""Sort lane routes and the concourse-width computed read (PRD 3.3, 3.13)."""

from flask import Blueprint, request

import calculations as calc
from auth import body, require_enum, require_int, require_str
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from response import paginate, success_list, success_object
from serializers import to_dict, to_list
from store import STORE

bp = Blueprint("lanes", __name__)

LANE_KINDS = ("PRIMARY", "SECONDARY", "IRREGULAR", "HAZMAT")
COMMODITY_CLASSES = ("GENERAL", "IRREGULAR", "HAZMAT", "PERISHABLE")


@bp.route("/airhub/lanes", methods=["POST"])
def create_lane():
    payload = body()
    hub = STORE.get("hubs", payload.get("hub_id"))
    if hub is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    code = require_str(payload, "lane_code")
    if any(l.get("hub_id") == hub["id"] and l.get("lane_code") == code
           for l in STORE.all("lanes")):
        raise ApiError(ERR_INVALID_REQUEST, "lane_code must be unique within the hub.")
    kind = require_enum(payload, "lane_kind", LANE_KINDS)
    capability = require_enum(payload, "commodity_capability", COMMODITY_CLASSES)
    capacity = require_int(payload, "capacity_weight_grams", minimum=1)
    certified = require_int(payload, "certified_until_minutes")
    start = require_int(payload, "turnout_start_minutes")
    end = require_int(payload, "turnout_end_minutes")
    if end <= start:
        raise ApiError(ERR_INVALID_REQUEST,
                       "turnout_end_minutes must be strictly greater than turnout_start_minutes.")
    lane = STORE.create("lanes", {
        "hub_id": hub["id"],
        "lane_code": code,
        "lane_kind": kind,
        "commodity_capability": capability,
        "capacity_weight_grams": capacity,
        "certified_until_minutes": certified,
        "turnout_start_minutes": start,
        "turnout_end_minutes": end,
        "status": "AVAILABLE",
        "lane_load_grams": 0,
    })
    return success_object(to_dict("lanes", lane), 201)


@bp.route("/airhub/lanes", methods=["GET"])
def list_lanes():
    rows = STORE.all("lanes")
    args = request.args
    for field in ("hub_id", "lane_kind", "status"):
        value = args.get(field)
        if value:
            rows = [r for r in rows if r.get(field) == value]
    page, limit, offset, total = paginate(rows, args)
    return success_list(to_list("lanes", page), limit, offset, total)


@bp.route("/airhub/lanes/concourse-width", methods=["GET"])
def concourse_width():
    hub_id = request.args.get("hub_id")
    lane_kind = request.args.get("lane_kind")
    if not hub_id or not lane_kind:
        raise ApiError(ERR_INVALID_REQUEST, "hub_id and lane_kind are required.")
    if STORE.get("hubs", hub_id) is None:
        raise ApiError("ERR_RESOURCE_NOT_FOUND")
    return success_object(calc.concourse_width(STORE, hub_id, lane_kind))


@bp.route("/airhub/lanes/<lane_id>", methods=["GET"])
def get_lane(lane_id):
    lane = STORE.get("lanes", lane_id)
    return success_object(to_dict("lanes", lane))


@bp.route("/airhub/lanes/<lane_id>/close", methods=["POST"])
def close_lane(lane_id):
    lane = STORE.get("lanes", lane_id)
    if lane.get("status") == "CLOSED":
        raise ApiError(ERR_INVALID_STATE)
    lane["status"] = "CLOSED"
    STORE.touch("lanes", lane)
    return success_object(to_dict("lanes", lane))


@bp.route("/airhub/lanes/<lane_id>/reopen", methods=["POST"])
def reopen_lane(lane_id):
    lane = STORE.get("lanes", lane_id)
    if lane.get("status") != "CLOSED":
        raise ApiError(ERR_INVALID_STATE)
    lane["status"] = "AVAILABLE"
    calc.recompute_lane(STORE, lane)
    return success_object(to_dict("lanes", lane))