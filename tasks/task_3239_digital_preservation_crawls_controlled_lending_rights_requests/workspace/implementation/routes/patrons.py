"""Patrons and accessibility credentials."""
from flask import Blueprint, request

import db
from errors import (
    ERR_DUPLICATE, ERR_INVALID_STATE, ERR_SO_DUTY_VIOLATION, ERR_UNAUTHORIZED,
    ERR_VALIDATION, not_found, raise_err, validation,
)
from middleware import require_roles
from models import new_id, serialize_credential, serialize_patron, stamp_new, touch
from response import iso_z, paginate, parse_pagination, success_list, success_object

bp = Blueprint("patrons", __name__)


@bp.post("/archive/patrons")
def create_patron():
    require_roles("Anonymous")
    body = request.get_json(silent=True) or {}
    email = body.get("email")
    full_name = body.get("full_name")
    if not isinstance(email, str) or not email:
        validation("email is required")
    if not isinstance(full_name, str) or not full_name:
        validation("full_name is required")
    if any(p["email"].lower() == email.lower() for p in db.patrons.values()):
        raise_err(ERR_DUPLICATE, "A patron with this email already exists")
    p = stamp_new()
    p.update({
        "email": email,
        "full_name": full_name,
        "status": "ACTIVE",
        "active_loan_count": 0,
        "strike_count": 0,
    })
    db.patrons[p["id"]] = p
    return success_object(serialize_patron(p), status=201)


@bp.get("/archive/patrons/<pid>")
def get_patron(pid):
    user_id, role = require_roles("Admin", "Patron")
    p = db.patrons.get(pid)
    if p is None:
        not_found("Patron not found")
    if role == "Patron" and user_id != pid:
        raise_err(ERR_UNAUTHORIZED, "Patrons may read only their own record")
    return success_object(serialize_patron(p))


@bp.post("/archive/accessibility-credentials")
def create_credential():
    user_id, _ = require_roles("Patron")
    body = request.get_json(silent=True) or {}
    patron_id = body.get("patron_id")
    cert_ref = body.get("certifier_reference")
    # Priority 2: entity-backed ownership — patron_id must equal X-User-ID.
    if patron_id is not None and patron_id != user_id:
        raise_err(ERR_UNAUTHORIZED, "patron_id must equal X-User-ID")
    # Priority 3: existence of referenced patron.
    if patron_id is not None and patron_id not in db.patrons:
        not_found("Patron not found")
    # Priority 6: schema validity.
    if not isinstance(patron_id, str) or not patron_id:
        validation("patron_id is required")
    if not isinstance(cert_ref, str) or not cert_ref:
        validation("certifier_reference is required")
    c = stamp_new()
    c.update({
        "patron_id": patron_id,
        "certifier_reference": cert_ref,
        "status": "PENDING_REVIEW",
        "decided_by": None,
        "decided_at": None,
    })
    db.credentials[c["id"]] = c
    return success_object(serialize_credential(c), status=201)


@bp.get("/archive/patrons/<pid>/accessibility-credentials")
def list_patron_credentials(pid):
    require_roles("Admin", "AccessibilityOfficer")
    if pid not in db.patrons:
        not_found("Patron not found")
    limit, offset = parse_pagination(request.args)
    status = request.args.get("status")
    rows = [c for c in db.credentials.values() if c["patron_id"] == pid]
    if status is not None:
        rows = [c for c in rows if c["status"] == status]
    rows.sort(key=lambda c: c["created_at"])
    page, total = paginate([serialize_credential(c) for c in rows], limit, offset)
    return success_list(page, limit, offset, total)


@bp.get("/archive/accessibility-credentials/<cid>")
def get_credential(cid):
    require_roles("Admin", "AccessibilityOfficer")
    c = db.credentials.get(cid)
    if c is None:
        not_found("Credential not found")
    return success_object(serialize_credential(c))


@bp.post("/archive/accessibility-credentials/<cid>/decide")
def decide_credential(cid):
    user_id, _ = require_roles("AccessibilityOfficer")
    c = db.credentials.get(cid)
    if c is None:
        not_found("Credential not found")
    body = request.get_json(silent=True) or {}
    decision = body.get("decision")
    # Priority 4: state gate per decision.
    if decision == "VERIFY" or decision == "REJECT":
        if c["status"] != "PENDING_REVIEW":
            raise_err(ERR_INVALID_STATE, "Credential is not PENDING_REVIEW")
    elif decision == "REVOKE":
        if c["status"] != "VERIFIED":
            raise_err(ERR_INVALID_STATE, "Credential is not VERIFIED")
    else:
        validation("decision must be VERIFY, REJECT, or REVOKE")
    # Priority 5: SoD — an officer may not VERIFY their own credential.
    if decision == "VERIFY" and user_id == c["patron_id"]:
        raise_err(ERR_SO_DUTY_VIOLATION, "An officer may not verify their own credential")
    c["decided_by"] = user_id
    c["decided_at"] = iso_z(db.now())
    if decision == "VERIFY":
        c["status"] = "VERIFIED"
    elif decision == "REJECT":
        c["status"] = "REJECTED"
    else:
        c["status"] = "REVOKED"
    touch(c)
    return success_object(serialize_credential(c))
