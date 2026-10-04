"""Ground feeder routes (PRD 3.8)."""

from flask import Blueprint, request

import calculations as calc
import services as svc
from auth import body, require_int, require_str
from errors import (
    ApiError,
    ERR_FEEDER_OVER_CAPACITY,
    ERR_FEEDER_WINDOW_CONFLICT,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_RESOURCE_NOT_FOUND,
)
from response import paginate, success_list, success_object
from serializers import to_dict, to_list
from store import STORE

bp = Blueprint("feeders", __name__)


def _hub(feeder):
    return STORE.get("hubs", feeder["hub_id"])


@bp.route("/airhub/feeders", methods=["POST"])
def create_feeder():
    payload = body()
    hub = STORE.get("hubs", payload.get("hub_id"))
    if hub is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND)
    code = require_str(payload, "feeder_code")
    if any(f.get("hub_id") == hub["id"] and f.get("feeder_code") == code
           for f in STORE.all("feeders")):
        raise ApiError(ERR_INVALID_REQUEST, "feeder_code must be unique within the hub.")
    require_str(payload, "origin_station_code")
    departure = require_int(payload, "scheduled_departure_minutes", minimum=1)
    capacity = require_int(payload, "stage_capacity_grams", minimum=1)
    window = require_int(payload, "window_minutes", minimum=1)
    feeder = STORE.create("feeders", {
        "hub_id": hub["id"],
        "feeder_code": code,
        "origin_station_code": payload["origin_station_code"],
        "scheduled_departure_minutes": departure,
        "stage_capacity_grams": capacity,
        "window_minutes": window,
        "status": "SCHEDULED",
        "staged_weight_grams": 0,
    })
    return success_object(to_dict("feeders", feeder), 201)


@bp.route("/airhub/feeders", methods=["GET"])
def list_feeders():
    rows = STORE.all("feeders")
    args = request.args
    for field in ("hub_id", "status"):
        value = args.get(field)
        if value:
            rows = [r for r in rows if r.get(field) == value]
    page, limit, offset, total = paginate(rows, args)
    return success_list(to_list("feeders", page), limit, offset, total)


@bp.route("/airhub/feeders/<feeder_id>", methods=["GET"])
def get_feeder(feeder_id):
    feeder = STORE.get("feeders", feeder_id)
    return success_object(to_dict("feeders", feeder))


@bp.route("/airhub/feeders/<feeder_id>/begin-staging", methods=["POST"])
def begin_staging(feeder_id):
    feeder = STORE.get("feeders", feeder_id)
    hub = _hub(feeder)
    if feeder.get("status") != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE)
    minute = STORE.minute()
    departure = int(feeder["scheduled_departure_minutes"])
    window = int(feeder["window_minutes"])
    # window conflict is a fiscal-capacity rule, checked before state gates
    for other in STORE.all("feeders"):
        if other["id"] == feeder["id"] or other.get("hub_id") != hub["id"]:
            continue
        if other.get("status") != "STAGING":
            continue
        if abs(int(other["scheduled_departure_minutes"]) - departure) <= window:
            raise ApiError(ERR_FEEDER_WINDOW_CONFLICT)
    if minute < departure - window:
        raise ApiError(ERR_INVALID_STATE)
    if minute >= departure:
        raise ApiError(ERR_INVALID_STATE)
    if not (int(hub["sort_window_open_minutes"]) <= minute
            < int(hub["sort_window_close_minutes"])):
        raise ApiError(ERR_INVALID_STATE)
    shift = calc.containing_shift(STORE, hub, minute)
    if shift is not None and shift.get("staffing_posture") == "SATURATED":
        raise ApiError(ERR_INVALID_STATE, "The containing shift is SATURATED.")
    feeder["status"] = "STAGING"
    calc.recompute_feeder(STORE, feeder)
    STORE.touch("feeders", feeder)
    return success_object(to_dict("feeders", feeder))


@bp.route("/airhub/feeders/<feeder_id>/stage-package", methods=["POST"])
def stage_package(feeder_id):
    feeder = STORE.get("feeders", feeder_id)
    payload = body()
    package = STORE.get("packages", payload.get("package_id"))
    if package is None:
        raise ApiError(ERR_RESOURCE_NOT_FOUND)
    if feeder.get("status") != "STAGING":
        raise ApiError(ERR_INVALID_STATE)
    if package.get("hub_id") != feeder["hub_id"]:
        raise ApiError(ERR_RESOURCE_NOT_FOUND)
    package["staged_feeder_id"] = feeder["id"]
    STORE.touch("packages", package)
    calc.recompute_feeder(STORE, feeder)
    STORE.touch("feeders", feeder)
    return success_object(to_dict("feeders", feeder))


@bp.route("/airhub/feeders/<feeder_id>/begin-loading", methods=["POST"])
def begin_loading(feeder_id):
    feeder = STORE.get("feeders", feeder_id)
    if feeder.get("status") != "STAGING":
        raise ApiError(ERR_INVALID_STATE)
    calc.recompute_feeder(STORE, feeder)
    if int(feeder["staged_weight_grams"]) > int(feeder["stage_capacity_grams"]):
        raise ApiError(ERR_FEEDER_OVER_CAPACITY)
    feeder["status"] = "LOADING"
    STORE.touch("feeders", feeder)
    return success_object(to_dict("feeders", feeder))


@bp.route("/airhub/feeders/<feeder_id>/depart", methods=["POST"])
def depart(feeder_id):
    feeder = STORE.get("feeders", feeder_id)
    hub = _hub(feeder)
    if feeder.get("status") != "LOADING":
        raise ApiError(ERR_INVALID_STATE)
    calc.recompute_feeder(STORE, feeder)
    ceiling = calc.feeder_depart_ceiling(feeder["stage_capacity_grams"])
    if int(feeder["staged_weight_grams"]) > ceiling:
        raise ApiError(ERR_FEEDER_OVER_CAPACITY)
    if hub.get("posture") not in ("OPEN", "CONGESTED"):
        raise ApiError(ERR_INVALID_STATE)
    staged = [p for p in STORE.all("packages")
              if p.get("staged_feeder_id") == feeder["id"]]
    feeder["status"] = "DEPARTED"
    feeder["staged_weight_grams"] = 0
    STORE.touch("feeders", feeder)
    for pkg in staged:
        pkg["commitment_status"] = "VOIDED"
        pkg["handling_status"] = "DIVERTED"
        pkg["final_commitment_minutes"] = None
        pkg["staged_feeder_id"] = None
        svc.refresh_package_postures(pkg)
        STORE.touch("packages", pkg)
        svc.new_failure(STORE, hub, pkg, "REVENUE_PRORATE")
    svc.hub_and_shifts(STORE, hub)
    return success_object(to_dict("feeders", feeder))


@bp.route("/airhub/feeders/<feeder_id>/cancel", methods=["POST"])
def cancel_feeder(feeder_id):
    feeder = STORE.get("feeders", feeder_id)
    status = feeder.get("status")
    if status not in ("SCHEDULED", "STAGING", "LOADING"):
        raise ApiError(ERR_INVALID_STATE)
    staged = [p for p in STORE.all("packages")
              if p.get("staged_feeder_id") == feeder["id"]]
    feeder["status"] = "CANCELLED"
    for pkg in staged:
        pkg["staged_feeder_id"] = None
        STORE.touch("packages", pkg)
    calc.recompute_feeder(STORE, feeder)
    STORE.touch("feeders", feeder)
    return success_object(to_dict("feeders", feeder))