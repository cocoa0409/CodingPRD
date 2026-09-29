"""Radiographic examination, escalation and voiding (PRD 3.6)."""

from flask import Blueprint, g

import common
import derive
import errors
import validate as v
from auth import (ALL_ROLES, AUTHORIZED_INSPECTOR, QC_INSPECTOR, acting_user,
                  endpoint)
from envelope import array_response, object_response, paged, query_filters
from errors import ApiError
from store import NDE_REPORTS, TANKS, WELD_SEAMS, WELDERS, new_row, touch
from util import now_logical

bp = Blueprint("nde", __name__)

METHODS = ("RT", "UT", "MT", "PT", "VT")
DECISIONS = ("ACCEPT", "REJECT")
DEFECT_TYPES = ("POROSITY", "SLAG_INCLUSION", "INCOMPLETE_PENETRATION",
                "CRACK", "UNDERCUT")


@bp.post("/nde-reports")
@endpoint((QC_INSPECTOR,))
def schedule_report():
    body = g.body
    seam_id = v.s_str(body, "weld_seam_id", required=True)
    method = v.s_enum(body, "method", METHODS, required=True)
    window_start = v.s_dt(body, "window_start_utc", required=True)
    window_end = v.s_dt(body, "window_end_utc", required=True)
    coverage_pct = v.s_num(body, "coverage_pct", required=True, gt=0, le=100)
    technician_stamp = v.s_str(body, "technician_stamp", required=True)
    seam = common.get_weld_seam(seam_id)

    if seam["status"] not in ("WELDED", "RT_ACCEPTED"):
        raise ApiError(errors.ERR_NDE_STATE_INVALID, 409,
                       "The seam is not available for examination.")
    for other in derive.reports_of_seam(seam["id"]):
        if other["status"] == "SCHEDULED":
            raise ApiError(errors.ERR_NDE_STATE_INVALID, 409,
                           "The seam already has a SCHEDULED examination.")

    if window_end <= window_start:
        raise ApiError(errors.ERR_INVALID_WINDOW, 409,
                       "window_end_utc must be strictly after "
                       "window_start_utc.")
    tank_id = derive.tank_id_of_seam(seam)
    if derive.rt_window_conflict(tank_id, method, window_start, window_end):
        raise ApiError(errors.ERR_EXAM_WINDOW_CONFLICT, 409,
                       "The buffered RT window conflicts with an existing "
                       "RT window on this tank.")

    report = new_row({
        "weld_seam_id": seam["id"],
        "method": method,
        "window_start_utc": window_start,
        "window_end_utc": window_end,
        "coverage_pct": coverage_pct,
        "technician_stamp": technician_stamp,
        "status": "SCHEDULED",
        "nonconformance_open": False,
        "indication_count": None,
        "film_count": None,
        "defect_type": None,
        "reported_by_user_id": None,
        "reported_at_utc": None,
        "void_reason": None,
    })
    NDE_REPORTS[report["id"]] = report

    seam["status"] = "EXAM_SCHEDULED"
    seam["last_nde_report_id"] = report["id"]
    touch(seam)
    course = derive.course_of_seam(seam)
    if course is not None:
        derive.rederive_course_status(course)
    return object_response(report, 201)


@bp.get("/nde-reports")
@endpoint(ALL_ROLES)
def list_reports():
    filters = query_filters("weld_seam_id", "method", "status",
                            "nonconformance_open")
    rows, limit, offset, total = paged(NDE_REPORTS.values(), filters)
    return array_response(rows, limit, offset, total)


@bp.get("/nde-reports/<nde_report_id>")
@endpoint(ALL_ROLES)
def read_report(nde_report_id):
    return object_response(common.get_nde_report(nde_report_id))


@bp.post("/nde-reports/<nde_report_id>/result")
@endpoint((QC_INSPECTOR,))
def report_result(nde_report_id):
    report = common.get_nde_report(nde_report_id)
    decision = v.s_enum(g.body, "decision", DECISIONS, required=True)
    indication_count = v.s_int(g.body, "indication_count", required=True, ge=0)
    film_count = v.s_int(g.body, "film_count", required=True, ge=0)
    defect_type = v.s_enum(g.body, "defect_type", DEFECT_TYPES, required=False)

    if report["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_NDE_STATE_INVALID, 409,
                       "Only a SCHEDULED examination may be reported.")

    seam = WELD_SEAMS.get(report["weld_seam_id"])
    welder = WELDERS.get(seam["welder_id"]) if seam["welder_id"] else None
    if (welder is not None
            and welder["qualified_by_user_id"] == acting_user()):
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                       "The inspector who qualified the welder may not judge "
                       "this examination.")

    if decision == "ACCEPT":
        if indication_count != 0:
            raise ApiError(errors.ERR_INDICATION_COUNT_INCONSISTENT, 409,
                           "An ACCEPT requires indication_count 0.")
    else:
        if indication_count < 1 or defect_type is None:
            raise ApiError(errors.ERR_INDICATION_COUNT_INCONSISTENT, 409,
                           "A REJECT requires at least one indication and a "
                           "defect_type.")

    report["indication_count"] = indication_count
    report["film_count"] = film_count
    report["reported_by_user_id"] = acting_user()
    report["reported_at_utc"] = now_logical()
    course = derive.course_of_seam(seam)
    tank = TANKS.get(course["tank_id"]) if course is not None else None

    if decision == "ACCEPT":
        report["status"] = "REPORTED_ACCEPT"
        report["defect_type"] = None
        report["nonconformance_open"] = False
        touch(report)
        for other in derive.reports_of_seam(seam["id"]):
            if other["id"] == report["id"]:
                continue
            if other["nonconformance_open"]:
                other["nonconformance_open"] = False
                touch(other)
        seam["status"] = "RT_ACCEPTED"
        touch(seam)
    else:
        report["status"] = "REPORTED_REJECT"
        report["defect_type"] = defect_type
        report["nonconformance_open"] = True
        touch(report)
        if seam["repair_cycle_count"] >= derive.MAX_REPAIR_CYCLES:
            seam["status"] = "REPLACEMENT_REQUIRED"
        else:
            seam["status"] = "RT_REJECTED"
        touch(seam)

    if course is not None:
        derive.rederive_course_status(course)
    if tank is not None:
        derive.recompute_reject_rate(tank)
        derive.recompute_posture(tank)
    return object_response(report)


@bp.post("/nde-reports/<nde_report_id>/void")
@endpoint((AUTHORIZED_INSPECTOR,))
def void_report(nde_report_id):
    report = common.get_nde_report(nde_report_id)
    void_reason = v.s_str(g.body, "void_reason", required=True)
    seam = WELD_SEAMS.get(report["weld_seam_id"])

    scheduled = report["status"] == "SCHEDULED"
    open_rejection = (report["status"] == "REPORTED_REJECT"
                      and report["nonconformance_open"]
                      and seam is not None
                      and seam["status"] == "RT_REJECTED")
    if not scheduled and not open_rejection:
        raise ApiError(errors.ERR_NDE_STATE_INVALID, 409,
                       "Only an unshot scheduled window or a still-open "
                       "rejection may be voided.")

    report["status"] = "VOIDED"
    report["nonconformance_open"] = False
    report["void_reason"] = void_reason
    touch(report)

    if scheduled:
        accepted_before = any(
            other["id"] != report["id"]
            and other["status"] == "REPORTED_ACCEPT"
            for other in derive.reports_of_seam(seam["id"]))
        seam["status"] = "RT_ACCEPTED" if accepted_before else "WELDED"
    else:
        seam["status"] = "WELDED"
    touch(seam)

    course = derive.course_of_seam(seam)
    if course is not None:
        derive.rederive_course_status(course)
        tank = TANKS.get(course["tank_id"])
        if tank is not None:
            derive.recompute_reject_rate(tank)
            derive.recompute_posture(tank)
    return object_response(report)
