"""Disciplinary reports: filing, segregation of duties, sanction cascade (3.8)."""
from flask import Blueprint, request

from auth import get_body, require_candidate_identity, require_roles
from envelope import ok, paginate
from errors import fail
from serializers import ser_disciplinary
from services import jurisdiction_by_code, recompute_eligibility
from store import db, new_id, stamp_new, touch

bp = Blueprint("disciplinary", __name__)


@bp.post("/disciplinary-reports")
def create_disciplinary_report():
    uid, _ = require_roles("BoardAdministrator")
    body = get_body()
    candidate_id = body.get("candidate_id")
    jc = body.get("jurisdiction_code")
    # Tier 3: body references and jurisdiction resolution.
    if candidate_id is not None and candidate_id not in db["candidates"]:
        fail("ERR_NOT_FOUND", "candidate_id does not resolve")
    if jc is not None and jurisdiction_by_code(jc) is None:
        fail("ERR_JURISDICTION_UNKNOWN", "jurisdiction_code does not resolve")
    # Tier 8: required fields; allegation must be non-empty.
    if candidate_id is None:
        fail("ERR_INVALID_REQUEST", "candidate_id is required")
    if jc is None:
        fail("ERR_INVALID_REQUEST", "jurisdiction_code is required")
    allegation = body.get("allegation")
    if not isinstance(allegation, str) or not allegation.strip():
        fail("ERR_INVALID_REQUEST", "allegation is required")
    rec = stamp_new({
        "id": new_id(),
        "candidate_id": candidate_id,
        "jurisdiction_code": jc,
        "allegation": allegation,
        # Opaque operator id of the filing BoardAdministrator; the resolver
        # must differ (segregation of duties).
        "filed_by_user_id": uid,
        "status": "OPEN",
        "resolution_notes": None,
    })
    db["disciplinary"][rec["id"]] = rec
    return ok(ser_disciplinary(rec), 201)


@bp.post("/disciplinary-reports/<rid>/resolve")
def resolve_disciplinary_report(rid):
    uid, _ = require_roles("NcarbAdministrator")
    rep = db["disciplinary"].get(rid)
    if rep is None:
        fail("ERR_NOT_FOUND", "disciplinary report not found")
    # Tier 4: OPEN only.
    if rep["status"] != "OPEN":
        fail("ERR_INVALID_STATE", "disciplinary report is no longer OPEN")
    # Tier 5: the resolver must differ from the filer.
    if uid == rep["filed_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES",
             "resolver must differ from the filing administrator")
    body = get_body()
    outcome = body.get("outcome")
    if outcome not in ("CLEAR", "SANCTION"):
        fail("ERR_INVALID_REQUEST", "outcome must be CLEAR or SANCTION")
    notes = body.get("resolution_notes")
    if notes is not None and not isinstance(notes, str):
        fail("ERR_INVALID_REQUEST", "resolution_notes must be a string")
    rep["status"] = "RESOLVED_CLEAR" if outcome == "CLEAR" else "RESOLVED_SANCTION"
    rep["resolution_notes"] = notes
    touch(rep)
    if outcome == "SANCTION":
        cand = db["candidates"].get(rep["candidate_id"])
        if cand is not None:
            # Link 1: record standing becomes FLAGGED (terminal).
            cand["record_standing"] = "FLAGGED"
            # Link 2: the non-REVOKED certificate (if any) is revoked.
            for cert in db["certificates"].values():
                if cert["candidate_id"] == cand["id"] and cert["status"] != "REVOKED":
                    cert["status"] = "REVOKED"
                    touch(cert)
                    # Link 3: every still-REQUESTED transmittal is cancelled;
                    # terminal LICENSE_GRANTED / LICENSE_DENIED are untouched.
                    for t in db["transmittals"].values():
                        if t["certificate_id"] == cert["id"] and t["status"] == "REQUESTED":
                            t["status"] = "CANCELLED"
                            touch(t)
            recompute_eligibility(cand)
            touch(cand)
    return ok(ser_disciplinary(rep))


@bp.get("/candidates/<cid>/disciplinary-reports")
def list_disciplinary_reports(cid):
    uid, role = require_roles("Candidate", "BoardAdministrator", "NcarbAdministrator")
    if role == "Candidate":
        require_candidate_identity(uid, cid)
    if cid not in db["candidates"]:
        fail("ERR_NOT_FOUND", "candidate not found")
    status = request.args.get("status")
    rows = [r for r in db["disciplinary"].values() if r["candidate_id"] == cid]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate([ser_disciplinary(r) for r in rows])
