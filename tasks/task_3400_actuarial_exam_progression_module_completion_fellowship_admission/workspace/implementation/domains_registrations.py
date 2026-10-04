"""Exam registrations, pass-mark settings, scoring and publication
(PRD §3.3). Parallel dimensions: logistics_status evolves independently of
grading_status. Fee on seat-hold, refund on cancel, waitlist promotion when a
seat frees on a REGISTRATION_OPEN window; publication grades all SAT rows.
"""

from decimal import Decimal

from flask import Blueprint, request

import serialize as SZ
import services as S
from auth import require, caller_candidate, check_owner
from errors import ApiError
from helpers import (body, ok_object, list_response, req_str, req_int,
                     req_mark)
from store import db, new_record, touch

bp = Blueprint("registrations", __name__)


@bp.post("/exam-registrations")
def create_registration():
    role, uid = require("Candidate")
    b = body()
    window_id = req_str(b, "exam_window_id")
    cand = caller_candidate(uid)
    window = db.exam_windows.get(window_id)
    if window is None:
        raise ApiError("ERR_EXAM_WINDOW_NOT_FOUND", 404, "exam window not found")
    if window["status"] != "REGISTRATION_OPEN":
        raise ApiError("ERR_WINDOW_NOT_OPEN", 422,
                       "window is not open for registration")
    if cand["status"] != "ACTIVE":
        raise ApiError("ERR_CANDIDATE_NOT_ACTIVE", 422,
                       "candidate is not ACTIVE")
    exam = db.exams.get(window["exam_id"])
    prereq_id = exam["prerequisite_exam_id"] if exam else None
    if prereq_id and not S.holds_credit_on(cand["id"], prereq_id):
        raise ApiError("ERR_PREREQUISITE_NOT_MET", 422,
                       "no credit held on the prerequisite exam")
    for r in db.exam_registrations.values():
        if (r["candidate_id"] == cand["id"]
                and r["exam_window_id"] == window["id"]
                and r["logistics_status"] in ("REGISTERED", "WAITLISTED")):
            raise ApiError("ERR_DUPLICATE_REGISTRATION", 409,
                           "an active registration already exists for this window")
    rec = new_record()
    rec.update({
        "candidate_id": cand["id"],
        "exam_window_id": window["id"],
        "grading_status": "PENDING",
        "raw_score": None,
        "result": None,
        "refund_cents": None,
        "cancel_reason": None,
        "sat_at": None,
    })
    # Capacity overflow waitlists (boundary: seats_held == capacity waitlists);
    # it is never an error.
    if S.seats_held(window) < window["capacity"]:
        rec["logistics_status"] = "REGISTERED"
        rec["fee_charged_cents"] = S.compute_fee_cents(window, db.clock)
    else:
        rec["logistics_status"] = "WAITLISTED"
        rec["fee_charged_cents"] = None
    db.exam_registrations[rec["id"]] = rec
    return ok_object(SZ.registration(rec), 201)


@bp.post("/exam-registrations/<rid>/cancel")
def cancel_registration_endpoint(rid):
    role, uid = require("Candidate", "Registrar")
    reg = db.exam_registrations.get(rid)
    if reg is None:
        raise ApiError("ERR_EXAM_REGISTRATION_NOT_FOUND", 404,
                       "exam registration not found")
    if role == "Candidate":
        check_owner(reg["candidate_id"] == uid)
    window = db.exam_windows.get(reg["exam_window_id"])
    if (reg["logistics_status"] not in ("REGISTERED", "WAITLISTED")
            or reg["grading_status"] != "PENDING"
            or window is None
            or window["status"] not in ("REGISTRATION_OPEN", "REGISTRATION_CLOSED")):
        raise ApiError("ERR_REGISTRATION_NOT_CANCELLABLE", 422,
                       "registration is not in a cancellable state")
    if role == "Candidate":
        cand = db.candidates.get(reg["candidate_id"])
        if cand is not None and cand["status"] != "ACTIVE":
            raise ApiError("ERR_CANDIDATE_NOT_ACTIVE", 422,
                           "candidate is not ACTIVE")
    S.cancel_registration(reg, window, "CANDIDATE", db.clock,
                          allow_promotion=True)
    return ok_object(SZ.registration(reg), 200)


@bp.post("/exam-registrations/<rid>/record-score")
def record_score(rid):
    require("ExamCommittee")
    b = body()
    raw = req_int(b, "raw_score", lo=0, hi=60)
    reg = db.exam_registrations.get(rid)
    if reg is None:
        raise ApiError("ERR_EXAM_REGISTRATION_NOT_FOUND", 404,
                       "exam registration not found")
    window = db.exam_windows.get(reg["exam_window_id"])
    if (reg["logistics_status"] != "SAT" or window is None
            or window["status"] != "SCORING"):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "scores can only be recorded for a SAT registration "
                       "while its window is SCORING")
    reg["raw_score"] = raw
    touch(reg)
    return ok_object(SZ.registration(reg), 200)


@bp.get("/candidates/<cid>/registrations")
def list_candidate_registrations(cid):
    role, uid = require("Candidate", "Registrar")
    cand = db.candidates.get(cid)
    if cand is None:
        raise ApiError("ERR_CANDIDATE_NOT_FOUND", 404, "candidate not found")
    if role == "Candidate":
        check_owner(cid == uid)
    items = sorted((r for r in db.exam_registrations.values()
                    if r["candidate_id"] == cid), key=lambda r: r["_seq"])
    f = request.args.get("logistics_status")
    if f is not None:
        items = [r for r in items if r["logistics_status"] == f]
    return list_response([SZ.registration(r) for r in items])


@bp.get("/exam-windows/<wid>/registrations")
def list_window_registrations(wid):
    require("Registrar", "ExamCommittee")
    window = db.exam_windows.get(wid)
    if window is None:
        raise ApiError("ERR_EXAM_WINDOW_NOT_FOUND", 404, "exam window not found")
    items = sorted((r for r in db.exam_registrations.values()
                    if r["exam_window_id"] == wid), key=lambda r: r["_seq"])
    f = request.args.get("logistics_status")
    if f is not None:
        items = [r for r in items if r["logistics_status"] == f]
    return list_response([SZ.registration(r) for r in items])


# ---------------------------------------------------------------------------
# Pass-mark settings (propose with OCC -> ratify -> publish)
# ---------------------------------------------------------------------------

@bp.post("/exam-windows/<wid>/pass-mark-settings")
def create_pass_mark_setting(wid):
    require("ExamCommittee")
    b = body()
    proposed = req_mark(b, "proposed_mark")
    expected = req_int(b, "expected_exam_window_version")
    window = db.exam_windows.get(wid)
    if window is None:
        raise ApiError("ERR_EXAM_WINDOW_NOT_FOUND", 404, "exam window not found")
    if expected != window["version"]:
        raise ApiError("ERR_STALE_WINDOW_VERSION", 412,
                       "expected_exam_window_version does not match the window's "
                       "current version")
    if window["status"] not in ("REGISTRATION_CLOSED", "TESTING", "SCORING"):
        raise ApiError("ERR_PASS_MARK_INVALID_STATE", 422,
                       "pass marks can only be proposed once registration has "
                       "closed")
    # Create-with-supersede: any PROPOSED/RATIFIED setting becomes SUPERSEDED.
    for s in sorted(db.pass_mark_settings.values(), key=lambda x: x["_seq"]):
        if (s["exam_window_id"] == window["id"]
                and s["status"] in ("PROPOSED", "RATIFIED")):
            s["status"] = "SUPERSEDED"
            touch(s)
    rec = new_record()
    rec.update({
        "exam_window_id": window["id"],
        "proposed_mark": proposed,
        "ratified_mark": None,
        "status": "PROPOSED",
    })
    db.pass_mark_settings[rec["id"]] = rec
    touch(window)  # creating a setting increments the window's version by 1
    return ok_object(SZ.pass_mark(rec), 201)


@bp.post("/pass-mark-settings/<pid>/ratify")
def ratify_pass_mark(pid):
    require("ExamCommittee")
    b = body()
    ratified = req_mark(b, "ratified_mark")
    setting = db.pass_mark_settings.get(pid)
    if setting is None:
        raise ApiError("ERR_PASS_MARK_SETTING_NOT_FOUND", 404,
                       "pass-mark setting not found")
    if setting["status"] != "PROPOSED":
        raise ApiError("ERR_PASS_MARK_INVALID_STATE", 422,
                       "only a PROPOSED pass mark can be ratified")
    setting["ratified_mark"] = ratified
    setting["status"] = "RATIFIED"
    touch(setting)
    return ok_object(SZ.pass_mark(setting), 200)


@bp.post("/pass-mark-settings/<pid>/publish")
def publish_pass_mark(pid):
    require("ExamCommittee")
    setting = db.pass_mark_settings.get(pid)
    if setting is None:
        raise ApiError("ERR_PASS_MARK_SETTING_NOT_FOUND", 404,
                       "pass-mark setting not found")
    window = db.exam_windows.get(setting["exam_window_id"])
    if (setting["status"] != "RATIFIED" or window is None
            or window["status"] != "SCORING"):
        raise ApiError("ERR_PASS_MARK_INVALID_STATE", 422,
                       "only a RATIFIED mark on a SCORING window can be published")
    setting["status"] = "PUBLISHED"
    touch(setting)
    window["status"] = "RESULTS_PUBLISHED"
    touch(window)
    mark = Decimal(str(setting["ratified_mark"]))
    for reg in sorted((r for r in db.exam_registrations.values()
                       if r["exam_window_id"] == window["id"]
                       and r["logistics_status"] == "SAT"),
                      key=lambda r: r["_seq"]):
        scaled = S.scaled_score_of(reg)
        reg["result"] = ("PASS" if (scaled is not None and scaled >= mark)
                         else "FAIL")
        reg["grading_status"] = "RELEASED"
        touch(reg)
    return ok_object(SZ.pass_mark(setting), 200)


@bp.get("/exam-windows/<wid>/pass-mark-settings")
def list_pass_mark_settings(wid):
    require("Registrar", "ExamCommittee")
    window = db.exam_windows.get(wid)
    if window is None:
        raise ApiError("ERR_EXAM_WINDOW_NOT_FOUND", 404, "exam window not found")
    items = sorted((s for s in db.pass_mark_settings.values()
                    if s["exam_window_id"] == wid), key=lambda s: s["_seq"])
    return list_response([SZ.pass_mark(s) for s in items])
