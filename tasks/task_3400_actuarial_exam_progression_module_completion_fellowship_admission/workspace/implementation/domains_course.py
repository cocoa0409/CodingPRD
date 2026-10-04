"""Professionalism course sessions and attendance (PRD §3.7): stage-gated
booking, same-UTC-calendar-date conflict rule (date equality, not interval
overlap), hard capacity ceiling, HELD sweep, Registrar verification.
"""

from flask import Blueprint, request

import constants as C
import serialize as SZ
import services as S
from auth import require, caller_candidate, check_owner
from errors import ApiError, bad_request
from helpers import (body, ok_object, list_response, req_str, req_int,
                     req_dt, req_enum)
from store import db, new_record, touch

bp = Blueprint("course", __name__)


@bp.post("/course-sessions")
def create_course_session():
    require("Registrar")
    b = body()
    session_code = req_str(b, "session_code")
    starts_at = req_dt(b, "starts_at")
    ends_at = req_dt(b, "ends_at")
    capacity = req_int(b, "capacity", lo=1)
    if any(s["session_code"] == session_code for s in db.course_sessions.values()):
        bad_request("session_code already exists")
    rec = new_record()
    rec.update({
        "session_code": session_code,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "capacity": capacity,
        "status": "SCHEDULED",
    })
    db.course_sessions[rec["id"]] = rec
    return ok_object(SZ.course_session(rec), 201)


@bp.post("/course-attendances")
def create_course_attendance():
    role, uid = require("Candidate")
    b = body()
    session_id = req_str(b, "course_session_id")
    cand = caller_candidate(uid)
    session = db.course_sessions.get(session_id)
    if session is None:
        raise ApiError("ERR_COURSE_SESSION_NOT_FOUND", 404,
                       "course session not found")
    if session["status"] != "SCHEDULED" or db.clock >= session["starts_at"]:
        raise ApiError("ERR_SESSION_NOT_BOOKABLE", 422,
                       "session is no longer bookable")
    if cand["status"] != "ACTIVE":
        raise ApiError("ERR_CANDIDATE_NOT_ACTIVE", 422,
                       "candidate is not ACTIVE")
    if cand["membership_tier"] not in ("ASSOCIATE", "FELLOW"):
        raise ApiError("ERR_REQUIRES_ASSOCIATE", 422,
                       "the professionalism course requires the ASSOCIATE or "
                       "FELLOW tier")
    day = session["starts_at"].date()
    for a in db.course_attendances.values():
        if (a["candidate_id"] == cand["id"]
                and a["status"] in ("BOOKED", "ATTENDED")):
            other = db.course_sessions.get(a["course_session_id"])
            if other is not None and other["starts_at"].date() == day:
                raise ApiError("ERR_SESSION_SAME_DAY_CONFLICT", 409,
                               "another attendance falls on the same calendar date")
    if S.attendance_booked(session) >= session["capacity"]:
        raise ApiError("ERR_SESSION_FULL", 409, "session is at capacity")
    rec = new_record()
    rec.update({
        "course_session_id": session["id"],
        "candidate_id": cand["id"],
        "status": "BOOKED",
        "verified_at": None,
        "verified_by": None,
    })
    db.course_attendances[rec["id"]] = rec
    return ok_object(SZ.course_attendance(rec), 201)


@bp.post("/course-attendances/<aid>/verify")
def verify_course_attendance(aid):
    role, uid = require("Registrar")
    b = body()
    outcome = req_enum(b, "outcome", C.ATTENDANCE_OUTCOMES)
    att = db.course_attendances.get(aid)
    if att is None:
        raise ApiError("ERR_COURSE_ATTENDANCE_NOT_FOUND", 404,
                       "course attendance not found")
    session = db.course_sessions.get(att["course_session_id"])
    if att["status"] != "BOOKED" or session is None or session["status"] != "HELD":
        raise ApiError("ERR_ATTENDANCE_NOT_VERIFIABLE", 422,
                       "attendance must be BOOKED and the session HELD")
    att["status"] = outcome
    att["verified_at"] = db.clock
    att["verified_by"] = uid
    touch(att)
    return ok_object(SZ.course_attendance(att), 200)


@bp.get("/course-attendances/<aid>")
def get_course_attendance(aid):
    role, uid = require("Candidate", "Registrar")
    att = db.course_attendances.get(aid)
    if att is None:
        raise ApiError("ERR_COURSE_ATTENDANCE_NOT_FOUND", 404,
                       "course attendance not found")
    if role == "Candidate":
        check_owner(att["candidate_id"] == uid)
    return ok_object(SZ.course_attendance(att), 200)


@bp.get("/course-attendances")
def list_course_attendances():
    role, uid = require("Candidate", "Registrar")
    items = sorted(db.course_attendances.values(), key=lambda a: a["_seq"])
    if role == "Candidate":
        items = [a for a in items if a["candidate_id"] == uid]
    f_session = request.args.get("course_session_id")
    f_cand = request.args.get("candidate_id")
    f_status = request.args.get("status")
    if f_session is not None:
        items = [a for a in items if a["course_session_id"] == f_session]
    if f_cand is not None:
        items = [a for a in items if a["candidate_id"] == f_cand]
    if f_status is not None:
        items = [a for a in items if a["status"] == f_status]
    return list_response([SZ.course_attendance(a) for a in items])
