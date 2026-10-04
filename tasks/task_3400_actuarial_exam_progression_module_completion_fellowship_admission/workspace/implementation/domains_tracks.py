"""Fellowship tracks, module definitions and module attempts (PRD §3.5):
stage gate to ASSOCIATE/FELLOW, one live enrollment per candidate, sequence
gate k requires k-1 PASSED, capstone gate requires CAPSTONE_ELIGIBLE, retake
cooldown (strictly-later blocks; equality allows), synchronous grading with
bubble-up.
"""

from datetime import timedelta

from flask import Blueprint, request

import constants as C
import serialize as SZ
import services as S
from auth import require, caller_candidate, check_owner
from errors import ApiError, bad_request
from helpers import (body, ok_object, list_response, req_str, req_int,
                     req_enum, opt_bool, opt_int)
from store import db, new_record, touch

bp = Blueprint("tracks", __name__)


@bp.post("/track-enrollments")
def create_track_enrollment():
    role, uid = require("Candidate")
    b = body()
    track_code = req_enum(b, "track_code", C.TRACK_CODES)
    cand = caller_candidate(uid)
    if cand["status"] != "ACTIVE":
        raise ApiError("ERR_CANDIDATE_NOT_ACTIVE", 422,
                       "candidate is not ACTIVE")
    if cand["membership_tier"] not in ("ASSOCIATE", "FELLOW"):
        raise ApiError("ERR_REQUIRES_ASSOCIATE", 422,
                       "track enrollment requires the ASSOCIATE or FELLOW tier")
    for t in db.track_enrollments.values():
        if (t["candidate_id"] == cand["id"]
                and t["status"] in ("ENROLLED", "CAPSTONE_ELIGIBLE")):
            raise ApiError("ERR_ENROLLMENT_ACTIVE_EXISTS", 409,
                           "an active enrollment already exists")
    rec = new_record()
    rec.update({
        "candidate_id": cand["id"],
        "track_code": track_code,
        "status": "ENROLLED",
    })
    db.track_enrollments[rec["id"]] = rec
    return ok_object(SZ.track_enrollment(rec), 201)


@bp.get("/candidates/<cid>/track-enrollments")
def list_candidate_enrollments(cid):
    role, uid = require("Candidate", "Registrar")
    cand = db.candidates.get(cid)
    if cand is None:
        raise ApiError("ERR_CANDIDATE_NOT_FOUND", 404, "candidate not found")
    if role == "Candidate":
        check_owner(cid == uid)
    items = sorted((t for t in db.track_enrollments.values()
                    if t["candidate_id"] == cid), key=lambda t: t["_seq"])
    f = request.args.get("status")
    if f is not None:
        items = [t for t in items if t["status"] == f]
    return list_response([SZ.track_enrollment(t) for t in items])


@bp.post("/modules")
def create_module():
    require("Registrar")
    b = body()
    module_code = req_str(b, "module_code")
    track_code = req_enum(b, "track_code", C.TRACK_CODES)
    sequence_index = req_int(b, "sequence_index", lo=1)
    title = req_str(b, "title")
    is_capstone = opt_bool(b, "is_capstone", False)
    passing_score = req_int(b, "passing_score", lo=1, hi=100)
    cooldown_days = opt_int(b, "cooldown_days", C.DEFAULT_COOLDOWN_DAYS, lo=0)
    if any(m["module_code"] == module_code for m in db.modules.values()):
        bad_request("module_code already exists")
    if any(m["track_code"] == track_code and m["sequence_index"] == sequence_index
           for m in db.modules.values()):
        bad_request("sequence_index must be unique within the track")
    rec = new_record()
    rec.update({
        "module_code": module_code,
        "track_code": track_code,
        "sequence_index": sequence_index,
        "title": title,
        "is_capstone": is_capstone,
        "passing_score": passing_score,
        "cooldown_days": cooldown_days,
    })
    db.modules[rec["id"]] = rec
    return ok_object(SZ.module(rec), 201)


@bp.post("/module-attempts")
def create_module_attempt():
    role, uid = require("Candidate")
    b = body()
    enrollment_id = req_str(b, "track_enrollment_id")
    module_id = req_str(b, "module_id")
    cand = caller_candidate(uid)
    enrollment = db.track_enrollments.get(enrollment_id)
    if enrollment is None:
        raise ApiError("ERR_TRACK_ENROLLMENT_NOT_FOUND", 404,
                       "track enrollment not found")
    module = db.modules.get(module_id)
    if module is None:
        raise ApiError("ERR_MODULE_NOT_FOUND", 404, "module not found")
    check_owner(enrollment["candidate_id"] == cand["id"])
    if module["track_code"] != enrollment["track_code"]:
        bad_request("module does not belong to the enrollment's track")
    if enrollment["status"] not in ("ENROLLED", "CAPSTONE_ELIGIBLE"):
        raise ApiError("ERR_ENROLLMENT_NOT_ACTIVE", 422,
                       "enrollment is not active")
    if cand["status"] != "ACTIVE":
        raise ApiError("ERR_CANDIDATE_NOT_ACTIVE", 422,
                       "candidate is not ACTIVE")
    if module["is_capstone"]:
        if enrollment["status"] != "CAPSTONE_ELIGIBLE":
            raise ApiError("ERR_MODULE_SEQUENCE_LOCKED", 422,
                           "capstone modules require CAPSTONE_ELIGIBLE")
    else:
        k = module["sequence_index"]
        if k > 1:
            prev = None
            for m in db.modules.values():
                if (m["track_code"] == module["track_code"]
                        and m["sequence_index"] == k - 1):
                    prev = m
                    break
            passed = prev is not None and any(
                a["module_id"] == prev["id"]
                and a["track_enrollment_id"] == enrollment["id"]
                and a["status"] == "PASSED"
                for a in db.module_attempts.values())
            if not passed:
                raise ApiError("ERR_MODULE_SEQUENCE_LOCKED", 422,
                               "sequence %s requires a PASSED attempt on "
                               "sequence %s" % (k, k - 1))
    # Retake cooldown: blocked while a FAILED attempt's submitted_at +
    # cooldown_days is strictly later than now; equality allows the retake.
    for a in db.module_attempts.values():
        if (a["track_enrollment_id"] == enrollment["id"]
                and a["module_id"] == module["id"]
                and a["status"] == "FAILED"
                and a["submitted_at"] is not None
                and a["submitted_at"] + timedelta(days=module["cooldown_days"])
                > db.clock):
            raise ApiError("ERR_MODULE_COOLDOWN_ACTIVE", 422,
                           "a failed attempt's cooldown is still running")
    prior = sum(1 for a in db.module_attempts.values()
                if a["track_enrollment_id"] == enrollment["id"]
                and a["module_id"] == module["id"])
    rec = new_record()
    rec.update({
        "track_enrollment_id": enrollment["id"],
        "module_id": module["id"],
        "attempt_number": prior + 1,
        "status": "IN_PROGRESS",
        "score": None,
        "submitted_at": None,
    })
    db.module_attempts[rec["id"]] = rec
    return ok_object(SZ.module_attempt(rec), 201)


@bp.post("/module-attempts/<aid>/submit")
def submit_module_attempt(aid):
    role, uid = require("Candidate")
    b = body()
    score = req_int(b, "score", lo=0, hi=100)
    attempt = db.module_attempts.get(aid)
    if attempt is None:
        raise ApiError("ERR_MODULE_ATTEMPT_NOT_FOUND", 404,
                       "module attempt not found")
    enrollment = db.track_enrollments.get(attempt["track_enrollment_id"])
    check_owner(enrollment is not None and enrollment["candidate_id"] == uid)
    if attempt["status"] != "IN_PROGRESS":
        bad_request("a decided attempt is terminal")
    module = db.modules.get(attempt["module_id"])
    attempt["score"] = score
    attempt["submitted_at"] = db.clock
    attempt["status"] = ("PASSED" if module is not None
                         and score >= module["passing_score"] else "FAILED")
    touch(attempt)
    if attempt["status"] == "PASSED" and enrollment is not None and module is not None:
        S.sync_enrollment_after_pass(enrollment, module)
    return ok_object(SZ.module_attempt(attempt), 200)


@bp.get("/module-attempts/<aid>")
def get_module_attempt(aid):
    role, uid = require("Candidate", "Registrar")
    attempt = db.module_attempts.get(aid)
    if attempt is None:
        raise ApiError("ERR_MODULE_ATTEMPT_NOT_FOUND", 404,
                       "module attempt not found")
    if role == "Candidate":
        enrollment = db.track_enrollments.get(attempt["track_enrollment_id"])
        check_owner(enrollment is not None
                    and enrollment["candidate_id"] == uid)
    return ok_object(SZ.module_attempt(attempt), 200)


@bp.get("/module-attempts")
def list_module_attempts():
    role, uid = require("Candidate", "Registrar")
    items = sorted(db.module_attempts.values(), key=lambda a: a["_seq"])
    if role == "Candidate":
        own = {t["id"] for t in db.track_enrollments.values()
               if t["candidate_id"] == uid}
        items = [a for a in items if a["track_enrollment_id"] in own]
    f_enr = request.args.get("track_enrollment_id")
    f_mod = request.args.get("module_id")
    f_status = request.args.get("status")
    if f_enr is not None:
        items = [a for a in items if a["track_enrollment_id"] == f_enr]
    if f_mod is not None:
        items = [a for a in items if a["module_id"] == f_mod]
    if f_status is not None:
        items = [a for a in items if a["status"] == f_status]
    return list_response([SZ.module_attempt(a) for a in items])
