"""Flock placement and molt (PRD §3.2). Placement runs its checks in the
pinned order: state -> quarantine -> certification -> placement timing ->
downtime -> program/housing -> capacity."""

from flask import Blueprint

from auth import authenticate, require_role
from calc import (
    GROWING_WEEKS,
    MOLT_MIN_AGE_WEEKS,
    PLACEMENT_MAX_AGE_WEEKS,
    complex_of_flock,
    house_of_flock,
    recompute_hen_inventory,
)
from db import STORE, touch
from errors import (
    ApiError,
    ERR_CERTIFICATION_REQUIRED,
    ERR_COMPLEX_QUARANTINED,
    ERR_HOUSE_IN_DOWNTIME,
    ERR_HOUSE_OVER_CAPACITY,
    ERR_INVALID_STATE,
    ERR_MOLT_NOT_ALLOWED,
    ERR_PLACEMENT_NOT_DUE,
    ERR_PLACEMENT_WINDOW_MISSED,
    ERR_PROGRAM_HOUSING_MISMATCH,
)
from helpers import get_flock
from serialize import serialize_flock
from util import success_object
from validate import get_body, validate_payload

bp = Blueprint("flocks", __name__)


@bp.route("/api/flocks/<fid>", methods=["GET"])
def read_flock(fid):
    authenticate()
    return success_object(serialize_flock(get_flock(fid)))


@bp.route("/api/flocks/<fid>/place", methods=["POST"])
def place_flock(fid):
    _uid, role = authenticate()
    require_role(role, {"ProductionPlanner"})
    flock = get_flock(fid)
    validate_payload(get_body(), {})
    house = house_of_flock(flock)
    complex_ = STORE.complexes.get(house["complex_id"]) if house else None
    clock = STORE.clock

    if flock["status"] != "PLANNED":
        raise ApiError(ERR_INVALID_STATE, 409, "flock is not PLANNED")
    if complex_ is not None and complex_["biosecurity_posture"] == "QUARANTINE":
        raise ApiError(
            ERR_COMPLEX_QUARANTINED, 409, "complex is under quarantine"
        )
    if flock["program"] in ("CAGE_FREE", "ORGANIC"):
        certified = False
        for cert in STORE.certifications.values():
            if (
                cert["house_id"] == house["id"]
                and cert["program"] == flock["program"]
                and cert["status"] == "PASSED"
                and cert.get("_dt_valid_from") is not None
                and cert["_dt_valid_from"] <= clock
                and cert.get("_dt_valid_until") is not None
                and clock < cert["_dt_valid_until"]
            ):
                certified = True
                break
        if not certified:
            raise ApiError(
                ERR_CERTIFICATION_REQUIRED,
                422,
                "no PASSED, currently valid certification for this program",
            )
    placement_date = flock["_dt_placement_date"]
    if clock < placement_date:
        raise ApiError(
            ERR_PLACEMENT_NOT_DUE, 422, "placement_date not yet reached"
        )
    age_weeks = (clock - placement_date).days // 7
    if age_weeks > PLACEMENT_MAX_AGE_WEEKS:
        raise ApiError(
            ERR_PLACEMENT_WINDOW_MISSED,
            422,
            "placement is more than 30 weeks past placement_date",
        )
    downtime_until = house.get("_dt_downtime_until")
    if downtime_until is not None and clock < downtime_until:
        raise ApiError(
            ERR_HOUSE_IN_DOWNTIME, 409, "house is in post-depopulation downtime"
        )
    if flock["program"] != house["housing_style"]:
        raise ApiError(
            ERR_PROGRAM_HOUSING_MISMATCH,
            422,
            "flock program must equal the house's housing_style",
        )
    if house["hen_inventory"] + flock["placed_hen_count"] > house["capacity_hens"]:
        raise ApiError(
            ERR_HOUSE_OVER_CAPACITY, 422, "house capacity would be exceeded"
        )

    flock["age_weeks"] = age_weeks
    flock["current_hen_count"] = flock["placed_hen_count"]
    flock["status"] = "GROWING" if age_weeks < GROWING_WEEKS else "LAYING"
    touch(flock)
    recompute_hen_inventory(house)
    return success_object(serialize_flock(flock))


@bp.route("/api/flocks/<fid>/molt", methods=["POST"])
def molt_flock(fid):
    _uid, role = authenticate()
    require_role(role, {"ProductionPlanner"})
    flock = get_flock(fid)
    validate_payload(get_body(), {})
    if flock["status"] != "LAYING":
        raise ApiError(ERR_INVALID_STATE, 409, "flock is not LAYING")
    if flock["age_weeks"] < MOLT_MIN_AGE_WEEKS or flock["molt_count"] != 0:
        raise ApiError(
            ERR_MOLT_NOT_ALLOWED,
            422,
            "molt requires age_weeks >= 50 and molt_count == 0",
        )
    flock["status"] = "MOLT"
    flock["molt_start_age_weeks"] = flock["age_weeks"]
    touch(flock)
    return success_object(serialize_flock(flock))
