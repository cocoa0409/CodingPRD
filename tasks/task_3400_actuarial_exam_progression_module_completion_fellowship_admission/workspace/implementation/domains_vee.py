"""Validation by Educational Experience (PRD §3.4): transcript submission and
AcademicReviewer transcript review. A topic is credited at most once; approval
requires grade_points >= 2.7 (the 2.70 boundary approves).
"""

from flask import Blueprint, request

import constants as C
import serialize as SZ
from auth import require, caller_candidate, check_owner
from errors import ApiError
from helpers import body, ok_object, list_response, req_str, req_enum, req_num, opt_str
from store import db, new_record, touch

bp = Blueprint("vee", __name__)


@bp.post("/vee-submissions")
def create_vee_submission():
    role, uid = require("Candidate")
    b = body()
    topic = req_enum(b, "topic", C.VEE_TOPICS)
    university = req_str(b, "university")
    course_title = req_str(b, "course_title")
    grade_points = req_num(b, "grade_points", lo=0.0, hi=4.0)
    cand = caller_candidate(uid)
    if cand["status"] != "ACTIVE":
        raise ApiError("ERR_CANDIDATE_NOT_ACTIVE", 422,
                       "candidate is not ACTIVE")
    for s in db.vee_submissions.values():
        if (s["candidate_id"] == cand["id"] and s["topic"] == topic
                and s["status"] == "APPROVED"):
            raise ApiError("ERR_VEE_TOPIC_ALREADY_CREDITED", 409,
                           "an APPROVED submission already exists for this topic")
    rec = new_record()
    rec.update({
        "candidate_id": cand["id"],
        "topic": topic,
        "university": university,
        "course_title": course_title,
        "grade_points": grade_points,
        "status": "SUBMITTED",
        "reviewer_note": None,
        "reviewed_at": None,
    })
    db.vee_submissions[rec["id"]] = rec
    return ok_object(SZ.vee_submission(rec), 201)


@bp.post("/vee-submissions/<sid>/review")
def review_vee_submission(sid):
    require("AcademicReviewer")
    b = body()
    decision = req_enum(b, "decision", C.VEE_DECISIONS)
    note = opt_str(b, "reviewer_note", None)
    sub = db.vee_submissions.get(sid)
    if sub is None:
        raise ApiError("ERR_VEE_SUBMISSION_NOT_FOUND", 404,
                       "VEE submission not found")
    if sub["status"] != "SUBMITTED":
        raise ApiError("ERR_VEE_NOT_REVIEWABLE", 422,
                       "only a SUBMITTED submission is reviewable")
    if decision == "APPROVE" and sub["grade_points"] < C.VEE_GRADE_MIN:
        raise ApiError("ERR_VEE_GRADE_BELOW_THRESHOLD", 422,
                       "grade_points below the 2.7 approval floor")
    sub["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    sub["reviewer_note"] = note
    sub["reviewed_at"] = db.clock
    touch(sub)
    return ok_object(SZ.vee_submission(sub), 200)


@bp.get("/candidates/<cid>/vee-submissions")
def list_candidate_vee_submissions(cid):
    role, uid = require("Candidate", "AcademicReviewer", "Registrar")
    cand = db.candidates.get(cid)
    if cand is None:
        raise ApiError("ERR_CANDIDATE_NOT_FOUND", 404, "candidate not found")
    if role == "Candidate":
        check_owner(cid == uid)
    items = sorted((s for s in db.vee_submissions.values()
                    if s["candidate_id"] == cid), key=lambda s: s["_seq"])
    f_topic = request.args.get("topic")
    f_status = request.args.get("status")
    if f_topic is not None:
        items = [s for s in items if s["topic"] == f_topic]
    if f_status is not None:
        items = [s for s in items if s["status"] == f_status]
    return list_response([SZ.vee_submission(s) for s in items])
