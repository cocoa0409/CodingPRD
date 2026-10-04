"""Submission endpoints (PRD 3.3): create attempt, read, list, submit,
tech-review, retake."""
from flask import Blueprint

import constants as C
import domain
import errors as E
import serializers as ser
from response import ok, ok_list
from store import DB, new_id, stamp_new, touch, now
from validation import (auth_headers, require_role, body, req_field,
                        pagination_params, paginate)

bp = Blueprint("submissions", __name__)

_READERS = [C.ROLE_CANDIDATE, C.ROLE_ASSESSOR, C.ROLE_SCORING_ADMIN,
            C.ROLE_BOARD_ADMIN]

_OPEN_ATTEMPT_STATES = ("IN_PROGRESS", "SUBMITTED", "RETURNED", "SCORING",
                        "ADJUDICATION_REQUIRED")


def _assessor_holds_assignment(assessor_id, submission_id):
    return any(x for x in DB.assignments.values()
               if x["assessor_id"] == assessor_id
               and x.get("submission_id") == submission_id
               and x["status"] in ("ASSIGNED", "SCORE_SUBMITTED", "FINALIZED"))


def _get_submission_or_404(submission_id):
    sub = DB.submissions.get(submission_id)
    if sub is None:
        E.fail(E.ERR_SUBMISSION_NOT_FOUND, 404,
               "Submission not found: %s" % submission_id)
    return sub


@bp.post("/cycles/<cycle_id>/submissions")
def create_submission(cycle_id):
    uid, role = auth_headers()
    require_role(role, [C.ROLE_CANDIDATE])
    cycle = DB.cycles.get(cycle_id)
    if cycle is None:
        E.fail(E.ERR_CYCLE_NOT_FOUND, 404, "Cycle not found: %s" % cycle_id)
    candidate = DB.candidates.get(uid)
    if candidate is None:
        E.fail(E.ERR_CANDIDATE_NOT_FOUND, 404, "Candidate not found: %s" % uid)
    if candidate["status"] != "ELIGIBLE":
        E.fail(E.ERR_CANDIDATE_NOT_ELIGIBLE, 409,
               "Only an ELIGIBLE candidate may begin a component attempt")
    if cycle["status"] != "OPEN":
        E.fail(E.ERR_CYCLE_NOT_OPEN, 409, "Cycle must be OPEN")
    data = body()
    component_code = req_field(data, "component_code")
    for prior in domain.triple_for(candidate["id"], cycle["id"], component_code):
        if prior["status"] in _OPEN_ATTEMPT_STATES:
            E.fail(E.ERR_ACTIVE_ATTEMPT_EXISTS, 409,
                   "Another attempt of this component is still open")
    component = next((c for c in cycle["components"]
                      if c["code"] == component_code), None)
    if component is None:
        E.fail(E.ERR_COMPONENT_NOT_IN_CYCLE, 422,
               "component_code %s is not part of this cycle" % component_code)
    attempt_number = len(domain.triple_for(candidate["id"], cycle["id"],
                                           component_code)) + 1
    sub = {
        "id": new_id(),
        "candidate_id": candidate["id"],
        "cycle_id": cycle["id"],
        "component_code": component_code,
        "kind": component["kind"],
        "attempt_number": attempt_number,
        "prior_submission_id": None,
        "status": "IN_PROGRESS",
        "final_score": None,
    }
    stamp_new(sub)
    DB.submissions[sub["id"]] = sub
    domain.ensure_certification(candidate["id"], cycle["id"])
    return ok(ser.submission(sub), 201)


@bp.get("/submissions/<submission_id>")
def get_submission(submission_id):
    uid, role = auth_headers()
    require_role(role, _READERS)
    sub = _get_submission_or_404(submission_id)
    if role == C.ROLE_CANDIDATE and sub["candidate_id"] != uid:
        E.fail(E.ERR_NOT_RESOURCE_OWNER, 403,
               "Candidates may read only their own submissions")
    if role == C.ROLE_ASSESSOR and not _assessor_holds_assignment(uid, sub["id"]):
        E.fail(E.ERR_NOT_RESOURCE_OWNER, 403,
               "Assessors may read a submission only while holding an assignment on it")
    return ok(ser.submission(sub))


@bp.get("/submissions")
def list_submissions():
    uid, role = auth_headers()
    require_role(role, [C.ROLE_CANDIDATE, C.ROLE_SCORING_ADMIN,
                        C.ROLE_BOARD_ADMIN])
    limit, offset = pagination_params()
    items = list(DB.submissions.values())
    candidate_filter = uid if role == C.ROLE_CANDIDATE else None
    from flask import request
    candidate_param = request.args.get("candidate_id")
    if role != C.ROLE_CANDIDATE and candidate_param is not None:
        candidate_filter = candidate_param
    if candidate_filter is not None:
        items = [s for s in items if s["candidate_id"] == candidate_filter]
    cycle_id = request.args.get("cycle_id")
    if cycle_id is not None:
        items = [s for s in items if s["cycle_id"] == cycle_id]
    prior = request.args.get("prior_submission_id")
    if prior is not None:
        items = [s for s in items if s["prior_submission_id"] == prior]
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, total = paginate(items, limit, offset)
    return ok_list([ser.submission(s) for s in page], limit, offset, total)


@bp.post("/submissions/<submission_id>/submit")
def submit_submission(submission_id):
    uid, role = auth_headers()
    require_role(role, [C.ROLE_CANDIDATE])
    sub = _get_submission_or_404(submission_id)
    if sub["candidate_id"] != uid:
        E.fail(E.ERR_NOT_RESOURCE_OWNER, 403,
               "Candidates may submit only their own submissions")
    # Pinned order (PRD 2.8): state gate before any temporal rule.
    if sub["status"] not in ("IN_PROGRESS", "RETURNED"):
        E.fail(E.ERR_SUBMISSION_NOT_SUBMITTABLE, 409,
               "Submission must be IN_PROGRESS or RETURNED to submit")
    cycle = DB.cycles[sub["cycle_id"]]
    if cycle["status"] != "OPEN":
        E.fail(E.ERR_CYCLE_NOT_OPEN, 409, "Cycle must be OPEN")
    if not (cycle["submission_window_open"] <= now()
            < cycle["submission_window_close"]):
        E.fail(E.ERR_SUBMISSION_WINDOW_CLOSED, 422,
               "Logical clock is outside the half-open submission window")
    if sub["kind"] == "PORTFOLIO":
        artifacts = [a for a in DB.artifacts.values()
                     if a["submission_id"] == sub["id"]]
        has_commentary = any(a["artifact_type"] == "WRITTEN_COMMENTARY"
                             for a in artifacts)
        has_evidence = any(a["artifact_type"] in ("VIDEO", "STUDENT_WORK")
                           for a in artifacts)
        # Pinned order: required-artifact check before release-form check.
        if not (has_commentary and has_evidence):
            E.fail(E.ERR_REQUIRED_ARTIFACT_MISSING, 422,
                   "Portfolio requires at least one WRITTEN_COMMENTARY and at "
                   "least one of VIDEO or STUDENT_WORK")
        needs_release = any(
            a["artifact_type"] in ("VIDEO", "STUDENT_WORK")
            and a["subject_student_count"] is not None
            and a["subject_student_count"] >= 1
            for a in artifacts)
        has_release = any(a["artifact_type"] == "RELEASE_FORM" for a in artifacts)
        if needs_release and not has_release:
            E.fail(E.ERR_RELEASE_FORM_MISSING, 422,
                   "A RELEASE_FORM artifact is required when students appear "
                   "in VIDEO or STUDENT_WORK evidence")
    sub["status"] = "SUBMITTED"
    touch(sub)
    return ok(ser.submission(sub))


@bp.post("/submissions/<submission_id>/tech-review")
def tech_review(submission_id):
    _, role = auth_headers()
    require_role(role, [C.ROLE_SCORING_ADMIN])
    sub = _get_submission_or_404(submission_id)
    if sub["status"] != "SUBMITTED":
        E.fail(E.ERR_SUBMISSION_NOT_REVIEWABLE, 409,
               "Submission must be SUBMITTED for technical review")
    data = body()
    decision = req_field(data, "decision")
    if decision == "ACCEPT":
        sub["status"] = "SCORING"
    elif decision == "RETURN":
        sub["status"] = "RETURNED"
    else:
        E.fail(E.ERR_INVALID_REQUEST, 400,
               "decision must be ACCEPT or RETURN")
    touch(sub)
    return ok(ser.submission(sub))


@bp.post("/submissions/<submission_id>/retake")
def retake_submission(submission_id):
    uid, role = auth_headers()
    require_role(role, [C.ROLE_CANDIDATE])
    sub = _get_submission_or_404(submission_id)
    if sub["candidate_id"] != uid:
        E.fail(E.ERR_NOT_RESOURCE_OWNER, 403,
               "Candidates may retake only their own submissions")
    if sub["status"] != "SCORED":
        E.fail(E.ERR_SUBMISSION_NOT_RETAKEABLE, 409,
               "Only a SCORED attempt may be retaken")
    cycle = DB.cycles[sub["cycle_id"]]
    if now() >= cycle["retake_window_close"]:
        E.fail(E.ERR_RETAKE_WINDOW_CLOSED, 422,
               "The retake window has closed (boundary is exclusive)")
    new_attempt_number = len(domain.triple_of(sub)) + 1
    if new_attempt_number > cycle["max_attempts_per_component"]:
        E.fail(E.ERR_RETAKE_LIMIT_REACHED, 422,
               "attempt_number would exceed max_attempts_per_component")
    new_sub = {
        "id": new_id(),
        "candidate_id": sub["candidate_id"],
        "cycle_id": sub["cycle_id"],
        "component_code": sub["component_code"],
        "kind": sub["kind"],
        "attempt_number": new_attempt_number,
        "prior_submission_id": sub["id"],
        "status": "IN_PROGRESS",
        "final_score": None,
    }
    stamp_new(new_sub)
    DB.submissions[new_sub["id"]] = new_sub
    cert = domain.certification_for(sub["candidate_id"], sub["cycle_id"])
    if cert is not None and cert["status"] == "DENIED":
        cert["status"] = "PENDING"
        cert["weighted_total_final"] = None
        touch(cert)
    return ok(ser.submission(new_sub), 201)
