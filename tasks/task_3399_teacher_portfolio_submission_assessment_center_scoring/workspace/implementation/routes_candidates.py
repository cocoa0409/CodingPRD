"""Candidate endpoints: POST /candidates (open self-registration),
GET /candidates/{id}, submit-eligibility, verify-eligibility (PRD 3.2)."""
from flask import Blueprint, request

import constants as C
import errors as E
import serializers as ser
from response import ok
from store import DB, new_id, stamp_new, touch
from validation import auth_headers, require_role, body, req_field, as_number, as_int

bp = Blueprint("candidates", __name__)

_READERS = [C.ROLE_CANDIDATE, C.ROLE_SCORING_ADMIN, C.ROLE_BOARD_ADMIN,
            C.ROLE_INCENTIVE_ADMIN]


@bp.post("/candidates")
def create_candidate():
    # The one endpoint exempt from the header-presence gate (PRD 2.1). When a
    # role header IS supplied it must be Anonymous.
    role_hdr = request.headers.get("X-User-Role")
    if role_hdr is not None and str(role_hdr).strip() \
            and str(role_hdr).strip() != C.ROLE_ANONYMOUS:
        E.fail(E.ERR_INSUFFICIENT_PERMISSIONS, 403,
               "Only Anonymous callers may self-register")
    data = body()
    full_name = req_field(data, "full_name")
    email = req_field(data, "email")
    license_number = req_field(data, "license_number")
    license_state = req_field(data, "license_state")
    district_code = req_field(data, "district_code")
    years_experience = as_int(req_field(data, "years_experience"), "years_experience")
    fte = as_number(data.get("fte_fraction", C.DEFAULT_FTE_FRACTION), "fte_fraction")
    if fte < C.FTE_MIN or fte > C.FTE_MAX:
        E.fail(E.ERR_INVALID_REQUEST, 400,
               "fte_fraction must lie in [0.5, 1.0]")
    candidate = {
        "id": new_id(),
        "full_name": full_name,
        "email": email,
        "license_number": license_number,
        "license_state": license_state,
        "district_code": district_code,
        "years_experience": years_experience,
        "fte_fraction": fte,
        "license_document_ref": None,
        "employer_verification_ref": None,
        "status": "REGISTERED",
        "eligibility_note": None,
    }
    stamp_new(candidate)
    DB.candidates[candidate["id"]] = candidate
    return ok(ser.candidate(candidate), 201)


@bp.get("/candidates/<candidate_id>")
def get_candidate(candidate_id):
    uid, role = auth_headers()
    require_role(role, _READERS)
    if role == C.ROLE_CANDIDATE and uid != candidate_id:
        E.fail(E.ERR_NOT_RESOURCE_OWNER, 403,
               "Candidates may read only their own record")
    candidate = DB.candidates.get(candidate_id)
    if candidate is None:
        E.fail(E.ERR_CANDIDATE_NOT_FOUND, 404,
               "Candidate not found: %s" % candidate_id)
    return ok(ser.candidate(candidate))


@bp.post("/candidates/<candidate_id>/submit-eligibility")
def submit_eligibility(candidate_id):
    uid, role = auth_headers()
    require_role(role, [C.ROLE_CANDIDATE])
    if uid != candidate_id:
        E.fail(E.ERR_NOT_RESOURCE_OWNER, 403,
               "Candidates may submit eligibility only for their own record")
    candidate = DB.candidates.get(candidate_id)
    if candidate is None:
        E.fail(E.ERR_CANDIDATE_NOT_FOUND, 404,
               "Candidate not found: %s" % candidate_id)
    if candidate["status"] not in ("REGISTERED", "ELIGIBILITY_DENIED"):
        E.fail(E.ERR_CANDIDATE_NOT_SUBMITTABLE, 409,
               "Candidate must be REGISTERED or ELIGIBILITY_DENIED to submit")
    data = body()
    license_ref = req_field(data, "license_document_ref")
    employer_ref = req_field(data, "employer_verification_ref")
    candidate["license_document_ref"] = license_ref
    candidate["employer_verification_ref"] = employer_ref
    candidate["status"] = "ELIGIBILITY_REVIEW"
    touch(candidate)
    return ok(ser.candidate(candidate))


@bp.post("/candidates/<candidate_id>/verify-eligibility")
def verify_eligibility(candidate_id):
    _, role = auth_headers()
    require_role(role, [C.ROLE_BOARD_ADMIN])
    candidate = DB.candidates.get(candidate_id)
    if candidate is None:
        E.fail(E.ERR_CANDIDATE_NOT_FOUND, 404,
               "Candidate not found: %s" % candidate_id)
    if candidate["status"] != "ELIGIBILITY_REVIEW":
        E.fail(E.ERR_CANDIDATE_NOT_IN_REVIEW, 409,
               "Candidate must be ELIGIBILITY_REVIEW to decide")
    data = body()
    decision = req_field(data, "decision")
    if decision == "APPROVE":
        if candidate["years_experience"] < C.MIN_TEACHING_YEARS:
            E.fail(E.ERR_EXPERIENCE_REQUIREMENT_NOT_MET, 422,
                   "Eligibility requires at least %d years of teaching "
                   "experience" % C.MIN_TEACHING_YEARS)
        candidate["status"] = "ELIGIBLE"
    elif decision == "REJECT":
        candidate["status"] = "ELIGIBILITY_DENIED"
    else:
        E.fail(E.ERR_INVALID_REQUEST, 400,
               "decision must be APPROVE or REJECT")
    candidate["eligibility_note"] = data.get("note")
    touch(candidate)
    return ok(ser.candidate(candidate))
