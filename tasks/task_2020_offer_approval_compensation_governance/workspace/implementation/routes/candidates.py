"""Candidate endpoints."""

from flask import Blueprint

import db
from errors import (
    raise_err, ERR_CANDIDATE_NOT_FOUND, ERR_NOT_RESOURCE_OWNER,
    ERR_CANDIDATE_HAS_ACTIVE_OFFER, ERR_CANDIDATE_EMAIL_EXISTS,
)
from middleware import (
    get_actor, require_role, get_json_body, validate_fields, req_string, req_int,
)
from response import success
from services import calc

bp = Blueprint("candidates", __name__)

READ_ROLES = ["Recruiter", "HiringManager", "CompAnalyst", "HRAdmin", "Candidate"]


@bp.route("/api/candidates", methods=["POST"])
def create():
    uid, role = get_actor()
    body = get_json_body()
    validate_fields(body, ["full_name", "email"], ["current_base_cents"])
    full_name = req_string(body, "full_name")
    email = req_string(body, "email")
    current_base = req_int(body, "current_base_cents", required=False, allow_zero=True)
    require_role(role, ["Recruiter"])
    for c in db.candidates.values():
        if c["email"].lower() == email.lower():
            raise_err(ERR_CANDIDATE_EMAIL_EXISTS, "Candidate email already registered")
    ts = db.now_ms()
    cand = {
        "id": db.new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "full_name": full_name,
        "email": email,
        "current_base_cents": current_base,
        "status": "PROSPECT",
    }
    db.candidates[cand["id"]] = cand
    return success(cand, status=201)


@bp.route("/api/candidates/<cand_id>", methods=["GET"])
def get_one(cand_id):
    uid, role = get_actor()
    require_role(role, READ_ROLES)
    if role == "Candidate" and uid != cand_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Candidates may only read their own record")
    cand = db.candidates.get(cand_id)
    if cand is None:
        raise_err(ERR_CANDIDATE_NOT_FOUND, "Candidate not found")
    return success(cand)


@bp.route("/api/candidates/<cand_id>/archive", methods=["POST"])
def archive(cand_id):
    uid, role = get_actor()
    if db.request_has_body():
        get_json_body()
    require_role(role, ["Recruiter"])
    cand = db.candidates.get(cand_id)
    if cand is None:
        raise_err(ERR_CANDIDATE_NOT_FOUND, "Candidate not found")
    if cand["status"] not in ("PROSPECT", "IN_PROCESS"):
        # ARCHIVED is terminal; HIRED candidates cannot be archived per the machine
        raise_err(ERR_CANDIDATE_HAS_ACTIVE_OFFER,
                  "Candidate cannot be archived from this status")
    for o in db.offers.values():
        if o["candidate_id"] == cand_id and o["status"] in calc.CANDIDATE_LIVE_STATUSES:
            raise_err(ERR_CANDIDATE_HAS_ACTIVE_OFFER,
                      "Candidate has an offer in a non-terminal status")
    cand["status"] = "ARCHIVED"
    calc.touch(cand)
    return success(cand)
