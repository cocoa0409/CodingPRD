"""Welders, field welding and the repair loop (PRD 3.5)."""

from flask import Blueprint, g

import common
import derive
import errors
import validate as v
from auth import (ALL_ROLES, AUTHORIZED_INSPECTOR, ERECTION_SUPERINTENDENT,
                  WELDER, acting_user, endpoint)
from envelope import array_response, object_response, paged, query_filters
from errors import ApiError
from store import SHELL_COURSES, TANKS, WELD_SEAMS, WELDERS, new_row, touch
from util import D, add_days, now_logical

bp = Blueprint("weld", __name__)

PROCESSES = ("SMAW", "SAW", "FCAW", "GTAW")
ACTIONS = ("RENEW", "REVOKE")
SEAM_TYPES = ("VERTICAL", "HORIZONTAL")
DEFAULT_CONTINUITY_LIMIT_DAYS = 180


@bp.post("/welders")
@endpoint((AUTHORIZED_INSPECTOR,))
def create_welder():
    body = g.body
    stamp = v.s_str(body, "welder_stamp", required=True)
    full_name = v.s_str(body, "full_name", required=True)
    process = v.s_enum(body, "process", PROCESSES, required=True)
    positions = v.s_str_array(body, "qualified_positions", required=True)
    welder_max = v.s_num(body, "welder_qualified_thickness_max_in",
                         required=True, gt=0)
    wps_number = v.s_str(body, "wps_number", required=True)
    wps_max = v.s_num(body, "wps_qualified_thickness_max_in", required=True,
                      gt=0)
    qualification_date = v.s_dt(body, "qualification_date_utc", required=True)
    limit_days = v.s_int(body, "continuity_limit_days", required=False,
                         default=DEFAULT_CONTINUITY_LIMIT_DAYS, ge=1)

    for other in WELDERS.values():
        if other["welder_stamp"] == stamp:
            raise common.duplicate("welder_stamp must be unique.")

    welder = new_row({
        "welder_stamp": stamp,
        "full_name": full_name,
        "process": process,
        "qualified_positions": positions,
        "welder_qualified_thickness_max_in": welder_max,
        "wps_number": wps_number,
        "wps_qualified_thickness_max_in": wps_max,
        "qualification_date_utc": qualification_date,
        "continuity_limit_days": limit_days,
        "last_weld_date_utc": qualification_date,
        "continuity_expires_at_utc": add_days(qualification_date, limit_days),
        "qualification_status": "QUALIFIED",
        "qualified_by_user_id": acting_user(),
        "revoked_at_utc": None,
    })
    WELDERS[welder["id"]] = welder
    return object_response(welder, 201)


@bp.get("/welders")
@endpoint(ALL_ROLES)
def list_welders():
    derive.refresh_all_welders()
    filters = query_filters("welder_stamp", "process", "qualification_status")
    rows, limit, offset, total = paged(WELDERS.values(), filters)
    return array_response(rows, limit, offset, total)


@bp.get("/welders/<welder_id>")
@endpoint(ALL_ROLES)
def read_welder(welder_id):
    welder = common.get_welder(welder_id)
    derive.refresh_welder(welder)
    return object_response(welder)


@bp.post("/welders/<welder_id>/qualification-actions")
@endpoint((AUTHORIZED_INSPECTOR,))
def welder_action(welder_id):
    welder = common.get_welder(welder_id)
    action = v.s_enum(g.body, "action", ACTIONS, required=True)
    effective = v.s_dt(g.body, "effective_date_utc", required=False)
    v.s_str(g.body, "remarks", required=False)
    derive.refresh_welder(welder)

    if welder["qualification_status"] == "REVOKED":
        raise ApiError(errors.ERR_WELDER_STATE_INVALID, 409,
                       "A revoked qualification accepts no further action.")
    if action == "RENEW" and welder["qualification_status"] != "LAPSED":
        raise ApiError(errors.ERR_WELDER_STATE_INVALID, 409,
                       "Only a LAPSED qualification may be renewed.")

    if action == "RENEW":
        base = effective if effective is not None else now_logical()
        welder["qualification_status"] = "QUALIFIED"
        welder["last_weld_date_utc"] = base
        welder["continuity_expires_at_utc"] = add_days(
            base, welder["continuity_limit_days"])
    else:
        welder["qualification_status"] = "REVOKED"
        welder["revoked_at_utc"] = now_logical()
    touch(welder)
    return object_response(welder)


@bp.post("/weld-seams")
@endpoint((ERECTION_SUPERINTENDENT,))
def create_seam():
    body = g.body
    course_id = v.s_str(body, "shell_course_id", required=True)
    seam_type = v.s_enum(body, "seam_type", SEAM_TYPES, required=True)
    label = v.s_str(body, "seam_label", required=True)
    length_in = v.s_num(body, "length_in", required=True, gt=0)
    sequence_index = v.s_int(body, "sequence_index", required=True, ge=1)
    predecessor_id = v.s_str(body, "predecessor_seam_id", required=False)
    course = common.get_shell_course(course_id)
    predecessor = (common.get_weld_seam(predecessor_id)
                   if predecessor_id is not None else None)

    if predecessor is not None:
        if derive.tank_id_of_seam(predecessor) != course["tank_id"]:
            raise common.cross_tank(
                "predecessor_seam_id must belong to the same tank.")
        seen = set()
        walk = predecessor
        while walk is not None:
            if walk["id"] in seen:
                raise ApiError(errors.ERR_SEAM_SEQUENCE_CYCLE, 409,
                               "The predecessor chain must terminate.")
            seen.add(walk["id"])
            nxt = walk.get("predecessor_seam_id")
            walk = WELD_SEAMS.get(nxt) if nxt else None

    for other in derive.seams_of_course(course["id"]):
        if other["seam_label"] == label:
            raise common.duplicate(
                "seam_label must be unique within the shell course.")
        if other["sequence_index"] == sequence_index:
            raise common.duplicate(
                "sequence_index must be unique within the shell course.")

    seam = new_row({
        "shell_course_id": course["id"],
        "seam_type": seam_type,
        "seam_label": label,
        "length_in": length_in,
        "sequence_index": sequence_index,
        "predecessor_seam_id": predecessor_id,
        "status": "FIT_READY",
        "repair_cycle_count": 0,
        "welder_id": None,
        "filler_lot": None,
        "welded_at_utc": None,
        "last_nde_report_id": None,
    })
    WELD_SEAMS[seam["id"]] = seam
    derive.rederive_course_status(course)
    return object_response(seam, 201)


@bp.get("/weld-seams")
@endpoint(ALL_ROLES)
def list_seams():
    filters = query_filters("shell_course_id", "welder_id",
                            "predecessor_seam_id", "seam_type", "status")
    rows, limit, offset, total = paged(WELD_SEAMS.values(), filters)
    return array_response(rows, limit, offset, total)


@bp.get("/weld-seams/<weld_seam_id>")
@endpoint(ALL_ROLES)
def read_seam(weld_seam_id):
    return object_response(common.get_weld_seam(weld_seam_id))


@bp.post("/weld-seams/<weld_seam_id>/weld-log")
@endpoint((WELDER,))
def weld_log(weld_seam_id):
    body = g.body
    claimed = body.get("welder_id")
    if not isinstance(claimed, str) or claimed != acting_user():
        raise ApiError(errors.ERR_WELDER_IDENTITY_MISMATCH, 403,
                       "welder_id must equal the acting X-User-ID.")
    seam = common.get_weld_seam(weld_seam_id)
    welder_id = v.s_str(body, "welder_id", required=True)
    filler_lot = v.s_str(body, "filler_lot", required=False)
    completed_at = v.s_dt(body, "completed_at_utc", required=False)
    welder = common.get_welder(welder_id)

    course = derive.course_of_seam(seam)
    tank = TANKS.get(course["tank_id"]) if course is not None else None

    if seam["status"] == "REPLACEMENT_REQUIRED":
        raise ApiError(errors.ERR_REPAIR_LIMIT_EXCEEDED, 409,
                       "The seam requires plate replacement.")
    if (seam["status"] not in ("FIT_READY", "REPAIR_IN_PROGRESS")
            or course["status"] not in ("FITTED", "WELDED")):
        raise ApiError(errors.ERR_SEAM_NOT_WELDABLE, 409,
                       "The seam is not in a weldable state.")
    common.require_not_frozen(tank)

    derive.refresh_welder(welder)
    if welder["qualification_status"] != "QUALIFIED":
        raise ApiError(errors.ERR_WELDER_NOT_QUALIFIED, 409,
                       "The welder's qualification is not current.")
    ceiling = min(D(welder["welder_qualified_thickness_max_in"]),
                  D(welder["wps_qualified_thickness_max_in"]))
    if D(course["plate_thickness_in"]) > ceiling:
        raise ApiError(errors.ERR_THICKNESS_OUT_OF_QUALIFIED_RANGE, 409,
                       "The course thickness exceeds a qualified ceiling.")

    package = derive.package_of_tank(tank["id"])
    if package is None or package["status"] != "ACCEPTED":
        raise ApiError(errors.ERR_FOUNDATION_NOT_ACCEPTED, 409,
                       "The tank's foundation package is not ACCEPTED.")

    predecessor_id = seam.get("predecessor_seam_id")
    if predecessor_id:
        predecessor = WELD_SEAMS.get(predecessor_id)
        if predecessor is None or predecessor["status"] != "RT_ACCEPTED":
            raise ApiError(errors.ERR_WELD_SEQUENCE_VIOLATION, 409,
                           "The predecessor seam is not yet RT_ACCEPTED.")

    welded_at = completed_at if completed_at is not None else now_logical()
    if seam["status"] == "REPAIR_IN_PROGRESS":
        seam["repair_cycle_count"] = seam["repair_cycle_count"] + 1
    seam["status"] = "WELDED"
    seam["welder_id"] = welder["id"]
    seam["filler_lot"] = filler_lot
    seam["welded_at_utc"] = welded_at
    touch(seam)

    welder["qualification_status"] = "QUALIFIED"
    welder["last_weld_date_utc"] = welded_at
    welder["continuity_expires_at_utc"] = add_days(
        welded_at, welder["continuity_limit_days"])
    touch(welder)

    derive.rederive_course_status(course)
    return object_response(seam)


@bp.post("/weld-seams/<weld_seam_id>/repair-start")
@endpoint((ERECTION_SUPERINTENDENT,))
def repair_start(weld_seam_id):
    seam = common.get_weld_seam(weld_seam_id)
    v.s_str(g.body, "defect_disposition", required=True)
    v.s_str(g.body, "remarks", required=False)

    if seam["status"] == "REPLACEMENT_REQUIRED":
        raise ApiError(errors.ERR_REPAIR_LIMIT_EXCEEDED, 409,
                       "The seam requires plate replacement.")
    if seam["status"] != "RT_REJECTED":
        raise ApiError(errors.ERR_SEAM_STATE_INVALID, 409,
                       "Only an RT_REJECTED seam may be opened for repair.")

    seam["status"] = "REPAIR_IN_PROGRESS"
    touch(seam)
    course = derive.course_of_seam(seam)
    if course is not None:
        derive.rederive_course_status(course)
    return object_response(seam)
