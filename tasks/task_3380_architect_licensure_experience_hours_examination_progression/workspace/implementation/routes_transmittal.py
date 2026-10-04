"""Reciprocal transmittal of certificates to jurisdiction boards (PRD 3.8)."""
from flask import Blueprint, request

from auth import get_body, require_candidate_identity, require_roles
from envelope import ok, paginate
from errors import fail
from serializers import ser_transmittal
from services import jurisdiction_by_code, open_disciplinary_count
from store import db, new_id, stamp_new, touch

bp = Blueprint("transmittal", __name__)


@bp.post("/certificates/<cert_id>/transmittals")
def create_transmittal(cert_id):
    uid, _ = require_roles("Candidate")
    cert = db["certificates"].get(cert_id)
    if cert is None:
        fail("ERR_NOT_FOUND", "certificate not found")
    require_candidate_identity(uid, cert["candidate_id"])
    body = get_body()
    jc = body.get("jurisdiction_code")
    # Tier 3: jurisdiction resolution.
    if jc is not None and jurisdiction_by_code(jc) is None:
        fail("ERR_JURISDICTION_UNKNOWN", "jurisdiction_code does not resolve")
    # Tier 4: certificate must be ACTIVE at request time.
    if cert["status"] != "ACTIVE":
        fail("ERR_CERTIFICATE_NOT_ACTIVE", "certificate is not ACTIVE")
    # Tier 5: no OPEN disciplinary report against the candidate.
    if open_disciplinary_count(cert["candidate_id"]) > 0:
        fail("ERR_OPEN_DISCIPLINARY_BLOCK",
             "an OPEN disciplinary report blocks transmittal")
    if jc is None:
        fail("ERR_INVALID_REQUEST", "jurisdiction_code is required")
    # Tier 8: only one unanswered (REQUESTED) transmittal per destination.
    for t in db["transmittals"].values():
        if (t["certificate_id"] == cert_id and t["jurisdiction_code"] == jc
                and t["status"] == "REQUESTED"):
            fail("ERR_TRANSMITTAL_DUPLICATE",
                 "a REQUESTED transmittal to that jurisdiction already exists")
    rec = stamp_new({
        "id": new_id(),
        "certificate_id": cert_id,
        "jurisdiction_code": jc,
        "status": "REQUESTED",
        "denial_reason": None,
    })
    db["transmittals"][rec["id"]] = rec
    return ok(ser_transmittal(rec), 201)


@bp.get("/certificates/<cert_id>/transmittals")
def list_transmittals(cert_id):
    uid, role = require_roles("Candidate", "BoardAdministrator", "NcarbAdministrator")
    cert = db["certificates"].get(cert_id)
    if cert is None:
        fail("ERR_NOT_FOUND", "certificate not found")
    if role == "Candidate":
        require_candidate_identity(uid, cert["candidate_id"])
    status = request.args.get("status")
    rows = [t for t in db["transmittals"].values()
            if t["certificate_id"] == cert_id]
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    return paginate([ser_transmittal(t) for t in rows])


@bp.post("/transmittals/<tid>/decide")
def decide_transmittal(tid):
    require_roles("BoardAdministrator")
    t = db["transmittals"].get(tid)
    if t is None:
        fail("ERR_NOT_FOUND", "transmittal not found")
    # Tier 4: both outcomes are terminal; decide is legal only from REQUESTED.
    if t["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "transmittal is no longer REQUESTED")
    body = get_body()
    outcome = body.get("outcome")
    if outcome not in ("GRANT", "DENY"):
        fail("ERR_INVALID_REQUEST", "outcome must be GRANT or DENY")
    if outcome == "GRANT":
        # GRANT is permitted only while the certificate is still ACTIVE.
        cert = db["certificates"].get(t["certificate_id"])
        if cert is None or cert["status"] != "ACTIVE":
            fail("ERR_CERTIFICATE_NOT_ACTIVE", "certificate is not ACTIVE")
        t["status"] = "LICENSE_GRANTED"
    else:
        reason = body.get("denial_reason")
        if not isinstance(reason, str) or not reason.strip():
            fail("ERR_INVALID_REQUEST", "denial_reason is required when outcome is DENY")
        t["status"] = "LICENSE_DENIED"
        t["denial_reason"] = reason
    touch(t)
    return ok(ser_transmittal(t))
