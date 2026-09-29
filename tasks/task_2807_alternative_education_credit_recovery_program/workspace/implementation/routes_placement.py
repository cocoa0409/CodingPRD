"""Placement attendance, re-entry adjudication and exit (PRD 3.5, 3.9)."""
from flask import Blueprint

import derive
import validate as v
from auth import endpoint, scope_center, scope_school
from envelope import ok, ok_list
from errors import ApiError
from helpers import eq, get_placement, q
from services import exit_placement, rederive_center
from store import D, ordered, store, touch

bp = Blueprint("placements", __name__)

SEAT_HOLDING_STATES = ("ACTIVE", "RE_ENTRY_PENDING")


def _school_scope(ctx, placement):
    student = store.students.get(placement["student_id"])
    if student is not None:
        scope_school(ctx, student["home_school_id"])


@bp.get("/placements/<placement_id>")
@endpoint("PlacementCoordinator", "DistrictAdmin", "AltEdTeacher", "HomeSchoolCounselor",
          "Registrar")
def read_placement(ctx, placement_id):
    row = get_placement(placement_id)
    scope_center(ctx, row["center_id"])
    _school_scope(ctx, row)
    return ok(derive.ser_placement(row))


@bp.get("/placements")
@endpoint("PlacementCoordinator", "DistrictAdmin", "AltEdTeacher", "HomeSchoolCounselor",
          "Registrar")
def list_placements(ctx):
    rows = ordered(store.placements.values())
    if ctx.role == "PlacementCoordinator":
        rows = [r for r in rows if r["center_id"] == ctx.uid]
    if ctx.role == "HomeSchoolCounselor":
        rows = [r for r in rows
                if store.students[r["student_id"]]["home_school_id"] == ctx.uid]
    rows = eq(rows, "student_id", q("student_id"))
    rows = eq(rows, "center_id", q("center_id"))
    rows = eq(rows, "referral_id", q("referral_id"))
    rows = eq(rows, "status", q("status"))
    return ok_list(rows, derive.ser_placement)


@bp.post("/placements/<placement_id>/attendance")
@endpoint("AltEdTeacher")
def log_attendance(ctx, placement_id):
    placement = get_placement(placement_id)
    b = v.body()
    present_delta = v.req_int(b, "days_present_delta", 0, None)
    enrolled_delta = v.req_int(b, "days_enrolled_delta", 0, None)
    if placement["status"] not in SEAT_HOLDING_STATES:
        raise ApiError("ERR_PLACEMENT_STATE_INVALID",
                       "attendance may not be logged against a %s placement"
                       % placement["status"])
    placement["days_present"] = placement["days_present"] + present_delta
    placement["days_enrolled"] = placement["days_enrolled"] + enrolled_delta
    touch(placement)
    return ok(derive.ser_placement(placement))


@bp.post("/placements/<placement_id>/request-re-entry")
@endpoint("PlacementCoordinator", "DistrictAdmin")
def request_re_entry(ctx, placement_id):
    placement = get_placement(placement_id)
    scope_center(ctx, placement["center_id"])
    b = v.body()
    target = v.req_date(b, "target_re_entry_date")
    if placement["status"] != "ACTIVE":
        raise ApiError("ERR_PLACEMENT_STATE_INVALID",
                       "re-entry may only be requested for an ACTIVE placement")
    plan = derive.plan_of_student(placement["student_id"])
    if plan is None or derive.plan_posture(plan) == "OFF_TRACK":
        raise ApiError("ERR_PLAN_POSTURE_BLOCKS_RE_ENTRY",
                       "the graduation plan posture blocks re-entry")
    figures = derive.readiness_figures(placement)
    rate = figures["attendance_rate"]
    if rate is None or rate < D("0.9000"):
        raise ApiError("ERR_ATTENDANCE_BELOW_MINIMUM",
                       "attendance_rate must be at least 0.9000")
    if figures["readiness_score"] < D("0.7500"):
        raise ApiError("ERR_READINESS_BELOW_THRESHOLD",
                       "readiness_score must be at least 0.7500")
    if derive.placement_has_flagged_enrollment(placement["id"]):
        raise ApiError("ERR_INTEGRITY_HOLD",
                       "an enrollment of this placement is FLAGGED")
    placement["status"] = "RE_ENTRY_PENDING"
    placement["target_re_entry_date"] = target
    placement["re_entry_requested_by_user_id"] = ctx.uid
    touch(placement)
    return ok(derive.ser_placement(placement))


@bp.post("/placements/<placement_id>/approve-re-entry")
@endpoint("DistrictAdmin")
def approve_re_entry(ctx, placement_id):
    placement = get_placement(placement_id)
    b = v.body()
    actual = v.req_date(b, "actual_re_entry_date")
    if placement["re_entry_requested_by_user_id"] is not None and \
            ctx.uid == placement["re_entry_requested_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "the requester may not approve the re-entry")
    if placement["status"] != "RE_ENTRY_PENDING":
        raise ApiError("ERR_PLACEMENT_STATE_INVALID",
                       "only a RE_ENTRY_PENDING placement may be approved")
    center = store.centers[placement["center_id"]]
    old_posture = derive.center_posture(center)
    placement["status"] = "RE_ENTERED"
    placement["actual_re_entry_date"] = actual
    touch(placement)
    touch(center)
    rederive_center(center, old_posture)
    return ok(derive.ser_placement(placement))


@bp.post("/placements/<placement_id>/deny-re-entry")
@endpoint("DistrictAdmin")
def deny_re_entry(ctx, placement_id):
    placement = get_placement(placement_id)
    b = v.body()
    reason = v.req_str(b, "re_entry_denial_reason", 1, None)
    if placement["status"] != "RE_ENTRY_PENDING":
        raise ApiError("ERR_PLACEMENT_STATE_INVALID",
                       "only a RE_ENTRY_PENDING placement may be denied")
    placement["status"] = "ACTIVE"
    placement["re_entry_denial_reason"] = reason
    placement["target_re_entry_date"] = None
    placement["re_entry_requested_by_user_id"] = None
    touch(placement)
    return ok(derive.ser_placement(placement))


@bp.post("/placements/<placement_id>/exit")
@endpoint("PlacementCoordinator")
def exit_placement_route(ctx, placement_id):
    placement = get_placement(placement_id)
    scope_center(ctx, placement["center_id"])
    b = v.body()
    reason = v.req_str(b, "exit_reason", 1, None)
    if placement["status"] not in SEAT_HOLDING_STATES:
        raise ApiError("ERR_PLACEMENT_STATE_INVALID",
                       "a %s placement cannot be exited" % placement["status"])
    center = store.centers[placement["center_id"]]
    old_posture = derive.center_posture(center)
    exit_placement(placement, reason)
    touch(center)
    rederive_center(center, old_posture)
    return ok(derive.ser_placement(placement))
