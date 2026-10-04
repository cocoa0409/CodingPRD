"""Written project assessments and volunteer grading (PRD §3.6): fork/join
workflow. First grade SUBMITTED -> IN_REVIEW; second grade joins to DECIDED
when |g1-g2| <= 10 (mean, round-half-up) else forks to SPLIT; a third distinct
grader resolves a SPLIT (median). Segregation of duties: no grader twice.
"""

from decimal import Decimal

from flask import Blueprint, request

import constants as C
import serialize as SZ
import services as S
from auth import require, caller_candidate, check_owner
from errors import ApiError
from helpers import body, ok_object, list_response, req_str, req_int
from store import db, new_record, touch

bp = Blueprint("projects", __name__)


@bp.post("/project-assessments")
def create_project_assessment():
    role, uid = require("Candidate")
    b = body()
    enrollment_id = req_str(b, "track_enrollment_id")
    title = req_str(b, "title")
    cand = caller_candidate(uid)
    enrollment = db.track_enrollments.get(enrollment_id)
    if enrollment is None:
        raise ApiError("ERR_TRACK_ENROLLMENT_NOT_FOUND", 404,
                       "track enrollment not found")
    check_owner(enrollment["candidate_id"] == cand["id"])
    if cand["status"] != "ACTIVE":
        raise ApiError("ERR_CANDIDATE_NOT_ACTIVE", 422,
                       "candidate is not ACTIVE")
    if enrollment["status"] not in ("CAPSTONE_ELIGIBLE", "COMPLETED"):
        raise ApiError("ERR_PROJECT_REQUIRES_CAPSTONE", 422,
                       "project submission requires a CAPSTONE_ELIGIBLE or "
                       "COMPLETED enrollment")
    rec = new_record()
    rec.update({
        "candidate_id": cand["id"],
        "track_enrollment_id": enrollment["id"],
        "title": title,
        "status": "SUBMITTED",
        "grader_ids": [],
        "scores": [],
        "final_score": None,
        "result": None,
    })
    db.project_assessments[rec["id"]] = rec
    return ok_object(SZ.project_assessment(rec), 201)


@bp.post("/project-assessments/<pid>/grades")
def grade_project_assessment(pid):
    role, uid = require("Grader")
    b = body()
    score = req_int(b, "score", lo=0, hi=100)
    project = db.project_assessments.get(pid)
    if project is None:
        raise ApiError("ERR_PROJECT_ASSESSMENT_NOT_FOUND", 404,
                       "project assessment not found")
    if project["status"] not in ("SUBMITTED", "IN_REVIEW", "SPLIT"):
        raise ApiError("ERR_PROJECT_NOT_GRADABLE", 422,
                       "a DECIDED assessment is terminal")
    if uid in project["grader_ids"]:
        raise ApiError("ERR_GRADER_CONFLICT", 422,
                       "this grader has already graded the assessment")
    project["grader_ids"].append(uid)
    project["scores"].append(score)
    if project["status"] == "SUBMITTED":
        project["status"] = "IN_REVIEW"
    elif project["status"] == "IN_REVIEW":
        g1, g2 = project["scores"][0], project["scores"][1]
        if abs(g1 - g2) <= C.CONSENSUS_TOLERANCE:
            project["status"] = "DECIDED"
            project["final_score"] = int(S.rhu(Decimal(g1 + g2) / Decimal(2), 0))
            project["result"] = ("PASS" if project["final_score"]
                                 >= C.PROJECT_PASS_SCORE else "FAIL")
        else:
            project["status"] = "SPLIT"
    else:  # SPLIT -> resolver leg
        ordered = sorted(project["scores"][:3])
        project["final_score"] = ordered[1]  # median of three integers
        project["status"] = "DECIDED"
        project["result"] = ("PASS" if project["final_score"]
                             >= C.PROJECT_PASS_SCORE else "FAIL")
    touch(project)
    if project["status"] == "DECIDED" and project["result"] == "PASS":
        enrollment = db.track_enrollments.get(project["track_enrollment_id"])
        if enrollment is not None:
            S.sync_enrollment_after_project(enrollment)
    return ok_object(SZ.project_assessment(project), 200)


@bp.get("/project-assessments/<pid>")
def get_project_assessment(pid):
    role, uid = require("Candidate", "Registrar", "Grader")
    project = db.project_assessments.get(pid)
    if project is None:
        raise ApiError("ERR_PROJECT_ASSESSMENT_NOT_FOUND", 404,
                       "project assessment not found")
    if role == "Candidate":
        check_owner(project["candidate_id"] == uid)
    return ok_object(SZ.project_assessment(project), 200)


@bp.get("/project-assessments")
def list_project_assessments():
    role, uid = require("Candidate", "Registrar", "Grader")
    items = sorted(db.project_assessments.values(), key=lambda p: p["_seq"])
    if role == "Candidate":
        items = [p for p in items if p["candidate_id"] == uid]
    f_cand = request.args.get("candidate_id")
    f_enr = request.args.get("track_enrollment_id")
    f_status = request.args.get("status")
    if f_cand is not None:
        items = [p for p in items if p["candidate_id"] == f_cand]
    if f_enr is not None:
        items = [p for p in items if p["track_enrollment_id"] == f_enr]
    if f_status is not None:
        items = [p for p in items if p["status"] == f_status]
    return list_response([SZ.project_assessment(p) for p in items])
