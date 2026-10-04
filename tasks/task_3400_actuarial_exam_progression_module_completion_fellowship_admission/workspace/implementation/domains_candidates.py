"""Candidate registration and record maintenance (PRD §3.1)."""

from flask import Blueprint

import serialize as SZ
from auth import require, check_owner
from errors import ApiError, bad_request
from helpers import body, ok_object, req_str
from store import db, new_record

bp = Blueprint("candidates", __name__)


@bp.post("/candidates")
def create_candidate():
    require("Anonymous")
    b = body()
    email = req_str(b, "email")
    full_name = req_str(b, "full_name")
    # PRD §3.1: email must be well-formed — exactly one '@' separating a
    # non-empty local part and a non-empty domain part.
    parts = email.split("@")
    if len(parts) != 2 or not parts[0] or not parts[1]:
        bad_request("email is not a well-formed address")
    if any(c["email"] == email for c in db.candidates.values()):
        bad_request("email is already registered")
    rec = new_record()
    rec.update({
        "email": email,
        "full_name": full_name,
        "membership_tier": "CANDIDATE",
        "status": "ACTIVE",
        "suspended_until": None,
        "associate_admitted_at": None,
        "fellow_admitted_at": None,
        "last_evaluated_at": None,
    })
    db.candidates[rec["id"]] = rec
    return ok_object(SZ.candidate(rec), 201)


@bp.get("/candidates/<cid>")
def get_candidate(cid):
    role, uid = require("Candidate", "Registrar")
    cand = db.candidates.get(cid)
    if cand is None:
        raise ApiError("ERR_CANDIDATE_NOT_FOUND", 404, "candidate not found")
    if role == "Candidate":
        check_owner(cid == uid)
    return ok_object(SZ.candidate(cand), 200)
