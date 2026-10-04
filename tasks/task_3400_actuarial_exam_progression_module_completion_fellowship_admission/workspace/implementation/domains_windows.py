"""Exam windows (PRD §3.3): scheduling with date ordering and the half-open
testing-interval overlap rule; reads expose version (OCC), seats_held and
waitlist_count.
"""

from flask import Blueprint, request

import serialize as SZ
from auth import require
from errors import ApiError, bad_request
from helpers import body, ok_object, list_response, req_str, req_int, req_dt
from store import db, new_record

bp = Blueprint("windows", __name__)


@bp.post("/exam-windows")
def create_exam_window():
    require("Registrar")
    b = body()
    exam_id = req_str(b, "exam_id")
    window_code = req_str(b, "window_code")
    opens = req_dt(b, "registration_opens_at")
    deadline = req_dt(b, "registration_deadline")
    testing_starts = req_dt(b, "testing_starts_at")
    testing_ends = req_dt(b, "testing_ends_at")
    capacity = req_int(b, "capacity", lo=1)
    base_fee = req_int(b, "base_fee_cents", lo=0)
    late_surcharge = req_int(b, "late_surcharge_cents", lo=0) \
        if b.get("late_surcharge_cents") is not None else 0
    if any(w["window_code"] == window_code for w in db.exam_windows.values()):
        bad_request("window_code already exists")
    if not (opens <= deadline <= testing_starts <= testing_ends):
        bad_request("window dates must be ordered: registration_opens_at <= "
                    "registration_deadline <= testing_starts_at <= testing_ends_at")
    exam = db.exams.get(exam_id)
    if exam is None:
        raise ApiError("ERR_EXAM_NOT_FOUND", 404, "exam not found")
    if exam["status"] != "ACTIVE":
        raise ApiError("ERR_EXAM_NOT_ACTIVE", 422,
                       "windows can only be scheduled for an ACTIVE exam")
    # Half-open [testing_starts_at, testing_ends_at) overlap; adjacency allowed.
    for w in db.exam_windows.values():
        if w["exam_id"] == exam["id"]:
            if testing_starts < w["testing_ends_at"] and \
                    w["testing_starts_at"] < testing_ends:
                raise ApiError("ERR_WINDOW_SCHEDULE_CONFLICT", 409,
                               "testing interval overlaps another window of this exam")
    rec = new_record()
    rec.update({
        "exam_id": exam["id"],
        "window_code": window_code,
        "registration_opens_at": opens,
        "registration_deadline": deadline,
        "testing_starts_at": testing_starts,
        "testing_ends_at": testing_ends,
        "capacity": capacity,
        "base_fee_cents": base_fee,
        "late_surcharge_cents": late_surcharge,
        "status": "SCHEDULED",
    })
    db.exam_windows[rec["id"]] = rec
    return ok_object(SZ.exam_window(rec), 201)


@bp.get("/exam-windows/<wid>")
def get_exam_window(wid):
    require("Registrar", "Candidate", "ExamCommittee")
    window = db.exam_windows.get(wid)
    if window is None:
        raise ApiError("ERR_EXAM_WINDOW_NOT_FOUND", 404, "exam window not found")
    return ok_object(SZ.exam_window(window), 200)


@bp.get("/exam-windows")
def list_exam_windows():
    require("Registrar", "Candidate", "ExamCommittee")
    items = sorted(db.exam_windows.values(), key=lambda w: w["_seq"])
    f_exam = request.args.get("exam_id")
    f_status = request.args.get("status")
    if f_exam is not None:
        items = [w for w in items if w["exam_id"] == f_exam]
    if f_status is not None:
        items = [w for w in items if w["status"] == f_status]
    return list_response([SZ.exam_window(w) for w in items])
