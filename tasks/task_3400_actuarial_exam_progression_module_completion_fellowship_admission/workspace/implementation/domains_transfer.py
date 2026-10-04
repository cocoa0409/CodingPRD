"""Transfer credit under mutual recognition (PRD §3.8): decided synchronously
at creation. BILATERAL -> min(claimed, 30); NON_BILATERAL -> min(half of
claimed rounded half-up, 15); UNRECOGNIZED -> 0 and DENIED.
"""

from decimal import Decimal

from flask import Blueprint, request

import constants as C
import serialize as SZ
import services as S
from auth import require, caller_candidate, check_owner
from errors import ApiError
from helpers import body, ok_object, list_response, req_enum, req_int
from store import db, new_record

bp = Blueprint("transfer", __name__)


@bp.post("/transfer-credit-requests")
def create_transfer_credit_request():
    role, uid = require("Candidate")
    b = body()
    source_body = req_enum(b, "source_body", C.SOURCE_BODIES)
    claimed_hours = req_int(b, "claimed_hours", lo=1)
    cand = caller_candidate(uid)
    if cand["status"] != "ACTIVE":
        raise ApiError("ERR_CANDIDATE_NOT_ACTIVE", 422,
                       "candidate is not ACTIVE")
    if source_body in C.BILATERAL_BODIES:
        agreement_class = "BILATERAL"
        granted = min(claimed_hours, C.BILATERAL_CAP)
        status = "GRANTED"
    elif source_body in C.NON_BILATERAL_BODIES:
        agreement_class = "NON_BILATERAL"
        half = int(S.rhu(Decimal(claimed_hours) * Decimal(C.NON_BILATERAL_RATIO), 0))
        granted = min(half, C.NON_BILATERAL_CAP)
        status = "GRANTED"
    else:
        agreement_class = "UNRECOGNIZED"
        granted = 0
        status = "DENIED"
    rec = new_record()
    rec.update({
        "candidate_id": cand["id"],
        "source_body": source_body,
        "claimed_hours": claimed_hours,
        "agreement_class": agreement_class,
        "granted_hours": granted,
        "status": status,
    })
    db.transfer_credit_requests[rec["id"]] = rec
    return ok_object(SZ.transfer_credit_request(rec), 201)


@bp.get("/candidates/<cid>/transfer-credit-requests")
def list_candidate_transfer_requests(cid):
    role, uid = require("Candidate", "Registrar")
    cand = db.candidates.get(cid)
    if cand is None:
        raise ApiError("ERR_CANDIDATE_NOT_FOUND", 404, "candidate not found")
    if role == "Candidate":
        check_owner(cid == uid)
    items = sorted((t for t in db.transfer_credit_requests.values()
                    if t["candidate_id"] == cid), key=lambda t: t["_seq"])
    f = request.args.get("status")
    if f is not None:
        items = [t for t in items if t["status"] == f]
    return list_response([SZ.transfer_credit_request(t) for t in items])
