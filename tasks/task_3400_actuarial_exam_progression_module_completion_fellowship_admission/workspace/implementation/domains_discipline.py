"""Discipline cases and sanctions (PRD §3.9): Registrar files, DisciplineBoard
resolves. SUSPENSION (requires ACTIVE candidate, suspension_days >= 1) runs the
suspension cascade with full-refund cancellations and waitlist promotions;
EXPULSION (ACTIVE or SUSPENDED) runs the terminal cascade with zero refunds and
enrollment withdrawal. DISMISSED/REPRIMAND mutate no candidate state.
"""

from datetime import timedelta

from flask import Blueprint, request

import constants as C
import serialize as SZ
import services as S
from auth import require, check_owner
from errors import ApiError
from helpers import body, ok_object, list_response, req_str, req_int, req_enum
from store import db, new_record, touch

bp = Blueprint("discipline", __name__)


@bp.post("/discipline-cases")
def create_discipline_case():
    require("Registrar")
    b = body()
    candidate_id = req_str(b, "candidate_id")
    charge = req_str(b, "charge")
    severity = req_int(b, "severity", lo=1, hi=10)
    cand = db.candidates.get(candidate_id)
    if cand is None:
        raise ApiError("ERR_CANDIDATE_NOT_FOUND", 404, "candidate not found")
    if cand["status"] == "EXPELLED":
        raise ApiError("ERR_CANDIDATE_NOT_ACTIVE", 422,
                       "cannot file a case against an EXPELLED candidate")
    rec = new_record()
    rec.update({
        "candidate_id": cand["id"],
        "charge": charge,
        "severity": severity,
        "status": "FILED",
        "resolution": None,
        "suspension_days": None,
        "suspended_until": None,
        "resolved_at": None,
    })
    db.discipline_cases[rec["id"]] = rec
    return ok_object(SZ.discipline_case(rec), 201)


@bp.post("/discipline-cases/<did>/sanction")
def sanction_discipline_case(did):
    require("DisciplineBoard")
    b = body()
    resolution = req_enum(b, "resolution", C.RESOLUTIONS)
    suspension_days = None
    if resolution == "SUSPENSION":
        # Conditional requirement: suspension_days >= 1 exactly when SUSPENSION.
        suspension_days = req_int(b, "suspension_days", lo=1)
    case = db.discipline_cases.get(did)
    if case is None:
        raise ApiError("ERR_DISCIPLINE_CASE_NOT_FOUND", 404,
                       "discipline case not found")
    if case["status"] != "FILED":
        raise ApiError("ERR_DISCIPLINE_ALREADY_RESOLVED", 422,
                       "case has already been resolved")
    cand = db.candidates.get(case["candidate_id"])
    if resolution == "SUSPENSION" and (cand is None or cand["status"] != "ACTIVE"):
        raise ApiError("ERR_CANDIDATE_NOT_ACTIVE", 422,
                       "a suspension requires an ACTIVE candidate")
    if resolution == "EXPULSION" and (cand is None
                                      or cand["status"] not in ("ACTIVE", "SUSPENDED")):
        raise ApiError("ERR_CANDIDATE_NOT_ACTIVE", 422,
                       "an expulsion requires an ACTIVE or SUSPENDED candidate")
    case["status"] = "RESOLVED"
    case["resolution"] = resolution
    case["resolved_at"] = db.clock
    if resolution == "SUSPENSION":
        case["suspension_days"] = suspension_days
        until = db.clock + timedelta(days=suspension_days)
        case["suspended_until"] = until
        cand["status"] = "SUSPENDED"
        cand["suspended_until"] = until
        touch(cand)
        # Suspension cascade: cancel live registrations with a full refund;
        # freed seats on REGISTRATION_OPEN windows promote the waitlist.
        for reg in sorted((r for r in db.exam_registrations.values()
                           if r["candidate_id"] == cand["id"]
                           and r["logistics_status"] in ("REGISTERED",
                                                         "WAITLISTED")),
                          key=lambda r: r["_seq"]):
            window = db.exam_windows.get(reg["exam_window_id"])
            if window is not None:
                S.cancel_registration(reg, window, "DISCIPLINE_SUSPENSION",
                                      db.clock, allow_promotion=True)
    elif resolution == "EXPULSION":
        cand["status"] = "EXPELLED"
        touch(cand)
        # Expulsion cascade: fees forfeited (refund 0); seats still promote;
        # live track enrollments withdraw.
        for reg in sorted((r for r in db.exam_registrations.values()
                           if r["candidate_id"] == cand["id"]
                           and r["logistics_status"] in ("REGISTERED",
                                                         "WAITLISTED")),
                          key=lambda r: r["_seq"]):
            window = db.exam_windows.get(reg["exam_window_id"])
            if window is not None:
                S.cancel_registration(reg, window, "DISCIPLINE_EXPULSION",
                                      db.clock, allow_promotion=True)
        for enr in sorted((t for t in db.track_enrollments.values()
                           if t["candidate_id"] == cand["id"]
                           and t["status"] in ("ENROLLED", "CAPSTONE_ELIGIBLE")),
                          key=lambda t: t["_seq"]):
            enr["status"] = "WITHDRAWN"
            touch(enr)
    touch(case)
    return ok_object(SZ.discipline_case(case), 200)


@bp.get("/candidates/<cid>/discipline-cases")
def list_candidate_discipline_cases(cid):
    role, uid = require("Candidate", "Registrar", "DisciplineBoard")
    cand = db.candidates.get(cid)
    if cand is None:
        raise ApiError("ERR_CANDIDATE_NOT_FOUND", 404, "candidate not found")
    if role == "Candidate":
        check_owner(cid == uid)
    items = sorted((d for d in db.discipline_cases.values()
                    if d["candidate_id"] == cid), key=lambda d: d["_seq"])
    f = request.args.get("status")
    if f is not None:
        items = [d for d in items if d["status"] == f]
    return list_response([SZ.discipline_case(d) for d in items])
