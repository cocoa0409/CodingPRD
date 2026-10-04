"""Education evaluation submission, review loop, resubmission (PRD 3.2)."""
from flask import Blueprint, request

from auth import get_body, require_candidate_identity, require_roles
from envelope import ok, paginate
from errors import fail
from serializers import ser_evaluation
from services import ALTERNATIVE_PATH_MIN_CREDITS, recompute_eligibility
from store import db, new_id, stamp_new, touch

bp = Blueprint("education", __name__)

PATH_TYPES = ("ACCREDITED_DEGREE", "ALTERNATIVE_PATH")


def _get_evaluation_or_404(eid):
    ev = db["evaluations"].get(eid)
    if ev is None:
        fail("ERR_NOT_FOUND", "education evaluation not found")
    return ev


@bp.post("/candidates/<cid>/education-evaluations")
def create_evaluation(cid):
    uid, _ = require_roles("Candidate")
    require_candidate_identity(uid, cid)
    cand = db["candidates"].get(cid)
    if cand is None:
        fail("ERR_NOT_FOUND", "candidate not found")
    # Tier 4: only one open (SUBMITTED) evaluation per candidate.
    for ev in db["evaluations"].values():
        if ev["candidate_id"] == cid and ev["status"] == "SUBMITTED":
            fail("ERR_EVALUATION_ALREADY_OPEN",
                 "candidate already has a SUBMITTED education evaluation")
    # Tier 8: shape and constraint checks.
    body = get_body()
    path_type = body.get("path_type")
    if path_type not in PATH_TYPES:
        fail("ERR_INVALID_REQUEST", "path_type must be ACCREDITED_DEGREE or ALTERNATIVE_PATH")
    institution = body.get("institution_name")
    if not isinstance(institution, str) or not institution.strip():
        fail("ERR_INVALID_REQUEST", "institution_name is required")
    credits = body.get("semester_credit_hours")
    if not isinstance(credits, int) or isinstance(credits, bool):
        fail("ERR_INVALID_REQUEST", "semester_credit_hours must be an integer")
    if path_type == "ALTERNATIVE_PATH" and credits < ALTERNATIVE_PATH_MIN_CREDITS:
        fail("ERR_ALTERNATIVE_CREDITS_INSUFFICIENT",
             "ALTERNATIVE_PATH requires at least 64 semester credit hours")
    rec = stamp_new({
        "id": new_id(),
        "candidate_id": cid,
        "path_type": path_type,
        "institution_name": institution,
        "semester_credit_hours": credits,
        "status": "SUBMITTED",
        "deficiency_notes": None,
        "review_count": 0,
    })
    db["evaluations"][rec["id"]] = rec
    return ok(ser_evaluation(rec), 201)


@bp.get("/candidates/<cid>/education-evaluations")
def list_evaluations(cid):
    uid, role = require_roles("Candidate", "NcarbAdministrator")
    if role == "Candidate":
        require_candidate_identity(uid, cid)
    if cid not in db["candidates"]:
        fail("ERR_NOT_FOUND", "candidate not found")
    status = request.args.get("status")
    rows = [e for e in db["evaluations"].values() if e["candidate_id"] == cid]
    if status is not None:
        rows = [e for e in rows if e["status"] == status]
    return paginate([ser_evaluation(e) for e in rows])


@bp.post("/education-evaluations/<eid>/review")
def review_evaluation(eid):
    require_roles("NcarbAdministrator")
    ev = _get_evaluation_or_404(eid)
    # Tier 4: review is only legal from SUBMITTED.
    if ev["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "evaluation is no longer SUBMITTED")
    body = get_body()
    decision = body.get("decision")
    if decision not in ("SATISFIED", "DEFICIENT"):
        fail("ERR_INVALID_REQUEST", "decision must be SATISFIED or DEFICIENT")
    if decision == "DEFICIENT":
        notes = body.get("deficiency_notes")
        if not isinstance(notes, str) or not notes.strip():
            fail("ERR_INVALID_REQUEST", "deficiency_notes is required when decision is DEFICIENT")
        ev["status"] = "DEFICIENT"
        ev["deficiency_notes"] = notes
    else:
        ev["status"] = "SATISFIED"
        ev["deficiency_notes"] = None
    ev["review_count"] += 1
    touch(ev)
    if decision == "SATISFIED":
        cand = db["candidates"].get(ev["candidate_id"])
        if cand is not None:
            changed = False
            if cand["education_status"] != "SATISFIED":
                cand["education_status"] = "SATISFIED"
                changed = True
            if recompute_eligibility(cand):
                changed = True
            if changed:
                touch(cand)
    return ok(ser_evaluation(ev))


@bp.post("/education-evaluations/<eid>/resubmit")
def resubmit_evaluation(eid):
    uid, _ = require_roles("Candidate")
    ev = _get_evaluation_or_404(eid)
    require_candidate_identity(uid, ev["candidate_id"])
    if ev["status"] != "DEFICIENT":
        fail("ERR_INVALID_STATE", "only a DEFICIENT evaluation may be resubmitted")
    body = get_body()
    # Resubmission returns to SUBMITTED, clears notes, and replaces any
    # input fields for which new values are supplied.
    if "path_type" in body and body["path_type"] is not None:
        if body["path_type"] not in PATH_TYPES:
            fail("ERR_INVALID_REQUEST", "path_type must be ACCREDITED_DEGREE or ALTERNATIVE_PATH")
        ev["path_type"] = body["path_type"]
    if "institution_name" in body and body["institution_name"] is not None:
        if not isinstance(body["institution_name"], str) or not body["institution_name"].strip():
            fail("ERR_INVALID_REQUEST", "institution_name must be a non-empty string")
        ev["institution_name"] = body["institution_name"]
    if "semester_credit_hours" in body and body["semester_credit_hours"] is not None:
        v = body["semester_credit_hours"]
        if not isinstance(v, int) or isinstance(v, bool):
            fail("ERR_INVALID_REQUEST", "semester_credit_hours must be an integer")
        ev["semester_credit_hours"] = v
    ev["status"] = "SUBMITTED"
    ev["deficiency_notes"] = None
    touch(ev)
    return ok(ser_evaluation(ev))
