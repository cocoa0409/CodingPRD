"""CPD attestation (PRD §3.8): member-only obligation, one attestation per
(candidate, cycle_year), required_hours fixed at creation (admission-year
proration with ceil, carryover capped at 10), Registrar verification drives
VERIFIED / SHORTFALL (>= boundary verifies; shortfall is curable).
"""

from flask import Blueprint, request

import serialize as SZ
import services as S
from auth import require, caller_candidate, check_owner
from errors import ApiError
from helpers import body, ok_object, list_response, req_int, req_num, opt_int
from store import db, new_record, touch

bp = Blueprint("cpd", __name__)


@bp.post("/cpd-attestations")
def create_cpd_attestation():
    role, uid = require("Candidate")
    b = body()
    cycle_year = req_int(b, "cycle_year")
    attested_hours = req_num(b, "attested_hours", lo=0)
    carryover_hours = opt_int(b, "carryover_hours", 0, lo=0)
    cand = caller_candidate(uid)
    if cand["status"] != "ACTIVE":
        raise ApiError("ERR_CANDIDATE_NOT_ACTIVE", 422,
                       "candidate is not ACTIVE")
    if cand["membership_tier"] not in ("ASSOCIATE", "FELLOW"):
        raise ApiError("ERR_CPD_NOT_MEMBER", 422,
                       "CPD attestation requires the ASSOCIATE or FELLOW tier")
    for a in db.cpd_attestations.values():
        if a["candidate_id"] == cand["id"] and a["cycle_year"] == cycle_year:
            raise ApiError("ERR_CPD_CYCLE_DUPLICATE", 409,
                           "an attestation already exists for this cycle year")
    required = S.cpd_required_hours(cand, cycle_year, carryover_hours)
    rec = new_record()
    rec.update({
        "candidate_id": cand["id"],
        "cycle_year": cycle_year,
        "attested_hours": attested_hours,
        "carryover_hours": carryover_hours,
        "required_hours": required,
        "verified_hours": None,
        "status": "ATTESTED",
        "verified_at": None,
    })
    db.cpd_attestations[rec["id"]] = rec
    return ok_object(SZ.cpd_attestation(rec), 201)


@bp.post("/cpd-attestations/<aid>/verify")
def verify_cpd_attestation(aid):
    require("Registrar")
    b = body()
    verified_hours = req_num(b, "verified_hours", lo=0)
    att = db.cpd_attestations.get(aid)
    if att is None:
        raise ApiError("ERR_CPD_ATTESTATION_NOT_FOUND", 404,
                       "CPD attestation not found")
    if att["status"] not in ("ATTESTED", "SHORTFALL"):
        raise ApiError("ERR_CPD_NOT_VERIFIABLE", 422,
                       "an already-VERIFIED attestation cannot be re-verified")
    att["verified_hours"] = verified_hours
    att["status"] = ("VERIFIED" if verified_hours >= att["required_hours"]
                     else "SHORTFALL")
    att["verified_at"] = db.clock
    touch(att)
    return ok_object(SZ.cpd_attestation(att), 200)


@bp.get("/candidates/<cid>/cpd-attestations")
def list_candidate_cpd_attestations(cid):
    role, uid = require("Candidate", "Registrar")
    cand = db.candidates.get(cid)
    if cand is None:
        raise ApiError("ERR_CANDIDATE_NOT_FOUND", 404, "candidate not found")
    if role == "Candidate":
        check_owner(cid == uid)
    items = sorted((a for a in db.cpd_attestations.values()
                    if a["candidate_id"] == cid), key=lambda a: a["_seq"])
    f_year = request.args.get("cycle_year")
    f_status = request.args.get("status")
    if f_year is not None:
        items = [a for a in items if str(a["cycle_year"]) == f_year]
    if f_status is not None:
        items = [a for a in items if a["status"] == f_status]
    return list_response([SZ.cpd_attestation(a) for a in items])
