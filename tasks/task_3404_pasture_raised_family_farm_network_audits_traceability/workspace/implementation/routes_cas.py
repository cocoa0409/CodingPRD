"""Corrective actions (PRD 3.3).

GET  /farm-network/audits/{id}/corrective-actions      (NM, Auditor, 200)
POST /farm-network/corrective-actions/{id}/submit      (NetworkManager, 200)
POST /farm-network/corrective-actions/{id}/verify      (Auditor, 200; SoD)
"""
from flask import Blueprint, request

import constants as C
import domain
import store
from auth import authenticate, authorize
from clock import now
from errors import ApiError
from responses import ok, ok_list
from serialize import ca_out
from validation import get_body, f_enum, f_str, MISSING, pagination

bp = Blueprint("corrective_actions", __name__, url_prefix="/farm-network")


@bp.route("/audits/<aid>/corrective-actions", methods=["GET"])
def list_cas(aid):
    uid, role = authenticate()
    authorize(role, ("NetworkManager", "Auditor"))
    audit = domain.get_audit_or_404(aid)
    limit, offset = pagination()
    status = request.args.get("status")
    severity = request.args.get("severity")
    rows = [ca for ca in store.corrective_actions.values() if ca["audit_id"] == audit["id"]]
    if status is not None:
        rows = [ca for ca in rows if ca["status"] == status]
    if severity is not None:
        rows = [ca for ca in rows if ca["severity"] == severity]
    page, total = domain.sorted_page(rows, limit, offset)
    return ok_list([ca_out(ca) for ca in page], limit, offset, total)


@bp.route("/corrective-actions/<cid>/submit", methods=["POST"])
def submit_ca(cid):
    uid, role = authenticate()
    authorize(role, ("NetworkManager",))
    ca = domain.get_ca_or_404(cid)
    data = get_body()
    evidence = f_str(data, "evidence_notes")
    if ca["status"] not in ("OPEN", "OVERDUE"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only an OPEN or OVERDUE corrective action can be submitted")
    ca["status"] = "SUBMITTED"
    ca["evidence_notes"] = evidence
    ca["version"] += 1
    ca["updated_at"] = now()
    return ok(ca_out(ca))


@bp.route("/corrective-actions/<cid>/verify", methods=["POST"])
def verify_ca(cid):
    uid, role = authenticate()
    authorize(role, ("Auditor",))
    ca = domain.get_ca_or_404(cid)
    # Segregation of duties (priority 4): the verifier must differ from the
    # auditor who completed the parent audit.
    audit = store.audits.get(ca["audit_id"])
    if audit is not None and uid == audit["auditor_user_id"]:
        raise ApiError("ERR_SOD_VIOLATION", 403,
                       "the verifying auditor must differ from the completing auditor")
    data = get_body()
    decision = f_enum(data, "decision", C.CA_DECISIONS)
    notes = f_str(data, "notes", required=False)
    if ca["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "only a SUBMITTED corrective action can be verified")
    if decision == "VERIFY_CLOSED":
        ca["status"] = "VERIFIED_CLOSED"
        ca["verified_by_user_id"] = uid
        ca["closed_at"] = now()
    else:  # REJECT -> rework loop back to OPEN, due_at unchanged
        ca["status"] = "OPEN"
    ca["version"] += 1
    ca["updated_at"] = now()
    return ok(ca_out(ca))
