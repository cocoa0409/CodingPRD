"""Credential applications (PRD §3.9): synchronous ASA/FSA evaluation with OCC
on Candidate.version. Every application stamps last_evaluated_at and bumps the
candidate version (even when DENIED); an approval additionally advances the
membership ladder and stamps the matching admitted_at (+1 more version).
"""

from flask import Blueprint, request

import constants as C
import serialize as SZ
import services as S
from auth import require, caller_candidate, check_owner
from errors import ApiError
from helpers import body, ok_object, list_response, req_int, req_enum
from store import db, new_record, touch

bp = Blueprint("credentials", __name__)


@bp.post("/credential-applications")
def create_credential_application():
    role, uid = require("Candidate")
    b = body()
    credential = req_enum(b, "credential", C.CREDENTIALS)
    expected = req_int(b, "expected_candidate_version")
    cand = caller_candidate(uid)
    if expected != cand["version"]:
        raise ApiError("ERR_STALE_CANDIDATE_VERSION", 412,
                       "expected_candidate_version does not match the "
                       "candidate's current version")
    if ((credential == "ASA"
         and cand["membership_tier"] in ("ASSOCIATE", "FELLOW"))
            or (credential == "FSA" and cand["membership_tier"] == "FELLOW")):
        raise ApiError("ERR_CREDENTIAL_ALREADY_HELD", 409,
                       "the credential applied for is already held")
    if cand["status"] != "ACTIVE":
        raise ApiError("ERR_CANDIDATE_NOT_ACTIVE", 422,
                       "candidate is not ACTIVE")
    deficiencies = S.evaluate_credential(cand, credential)
    approved = len(deficiencies) == 0
    rec = new_record()
    rec.update({
        "candidate_id": cand["id"],
        "credential": credential,
        "status": "APPROVED" if approved else "DENIED_DEFICIENCY",
        "deficiency_codes": deficiencies,
        "evaluated_at": db.clock,
    })
    db.credential_applications[rec["id"]] = rec
    # Evaluation stamp bumps the candidate version even on denial.
    cand["last_evaluated_at"] = db.clock
    touch(cand)
    if approved:
        if credential == "ASA":
            cand["membership_tier"] = "ASSOCIATE"
            cand["associate_admitted_at"] = db.clock
        else:
            cand["membership_tier"] = "FELLOW"
            cand["fellow_admitted_at"] = db.clock
        touch(cand)  # tier advancement bumps the version again
    return ok_object(SZ.credential_application(rec), 201)


@bp.get("/candidates/<cid>/credential-applications")
def list_candidate_credential_applications(cid):
    role, uid = require("Candidate", "Registrar")
    cand = db.candidates.get(cid)
    if cand is None:
        raise ApiError("ERR_CANDIDATE_NOT_FOUND", 404, "candidate not found")
    if role == "Candidate":
        check_owner(cid == uid)
    items = sorted((a for a in db.credential_applications.values()
                    if a["candidate_id"] == cid), key=lambda a: a["_seq"])
    f_cred = request.args.get("credential")
    f_status = request.args.get("status")
    if f_cred is not None:
        items = [a for a in items if a["credential"] == f_cred]
    if f_status is not None:
        items = [a for a in items if a["status"] == f_status]
    return list_response([SZ.credential_application(a) for a in items])
