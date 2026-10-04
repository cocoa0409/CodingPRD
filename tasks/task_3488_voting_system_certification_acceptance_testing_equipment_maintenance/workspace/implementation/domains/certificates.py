"""Certificate endpoints and lifecycle helpers (PRD 3.3).

Certificates are minted only by a campaign's CERTIFIED transition. Expiry is
lazy: certificate reads (single or list) flip an ACTIVE/SUSPENDED certificate
whose expires_at has been reached to EXPIRED with a version increment. Manual
suspension blocks future guards only; the software-modification cascade is the
one that fires downstream effects (domains.modifications).
"""
from datetime import timedelta

from flask import Blueprint

from auth import auth_context, peek_to_state, require_role, require_transition_actor
from constants import CERT_TTL_DAYS
from envelope import apply_filters, list_page, ok_object
from errors import err_invalid_state, err_not_found, raise_err
from store import db
from util import now, stamp_new, touch
from validation import body_json, no_extra, opt_str, req_enum

bp = Blueprint("certificates", __name__)

CERT_STATES = {"ACTIVE", "SUSPENDED", "REVOKED", "EXPIRED"}
CERT_ACTORS = {
    "SUSPENDED": {"CertificationAuthority"},
    "ACTIVE": {"CertificationAuthority"},
    "REVOKED": {"CertificationAuthority"},
}
CERT_FROM = {
    "SUSPENDED": {"ACTIVE"},
    "ACTIVE": {"SUSPENDED"},
    "REVOKED": {"ACTIVE", "SUSPENDED"},
}


def mint_certificate(campaign):
    """Create the ACTIVE certificate for a freshly CERTIFIED campaign."""
    issued = now()
    rec = stamp_new({})
    rec.update({
        "voting_system_id": campaign["voting_system_id"],
        "campaign_id": campaign["id"],
        "scope": "STATE" if campaign["state_code"] else "FEDERAL",
        "state_code": campaign["state_code"],
        "guidelines_baseline": campaign["guidelines_baseline"],
        "issued_at": issued,
        "expires_at": issued + timedelta(days=CERT_TTL_DAYS),
        "status": "ACTIVE",
    })
    db.certificates[rec["id"]] = rec
    return rec


def sweep_certificate(cert):
    """Lazy expiry: a read observing now >= expires_at flips to EXPIRED."""
    if cert["status"] in {"ACTIVE", "SUSPENDED"} and now() >= cert["expires_at"]:
        cert["status"] = "EXPIRED"
        touch(cert)


def get_certificate_or_404(cert_id):
    cert = db.certificates.get(cert_id)
    if cert is None:
        err_not_found("certificate not found")
    return cert


@bp.get("/evote/certificates")
def list_certificates():
    auth_context()
    for cert in db.certificates.values():
        sweep_certificate(cert)
    items = apply_filters(
        list(db.certificates.values()),
        {"voting_system_id", "campaign_id", "status", "scope"},
    )
    return list_page(items)


@bp.get("/evote/certificates/<cert_id>")
def get_certificate(cert_id):
    auth_context()
    cert = get_certificate_or_404(cert_id)
    sweep_certificate(cert)
    return ok_object(cert, 200)


def revoke_cascade(cert):
    """Cancel non-terminal procurements pinning this certificate (PRD 3.3)."""
    for proc in db.procurements.values():
        if proc["certificate_id"] == cert["id"] and proc["status"] in {"PLACED", "DELIVERED", "ACCEPTANCE_TESTING"}:
            proc["status"] = "CANCELLED"
            proc["status_reason"] = "CERTIFICATE_REVOKED"
            touch(proc)
            jurisdiction = db.jurisdictions.get(proc["jurisdiction_id"])
            if jurisdiction is not None:
                jurisdiction["encumbered_cents"] -= proc["total_price_cents"]
                jurisdiction["available_cents"] += proc["total_price_cents"]
                touch(jurisdiction)


@bp.post("/evote/certificates/<cert_id>/transitions")
def certificate_transition(cert_id):
    _, role = auth_context()
    require_role(role, {"CertificationAuthority"})
    ts = peek_to_state()
    require_transition_actor(role, ts, CERT_ACTORS)
    cert = get_certificate_or_404(cert_id)
    body = body_json()
    no_extra(body, {"to_state", "reason"})
    to_state = req_enum(body, "to_state", CERT_STATES)
    opt_str(body, "reason")  # declared, accepted, not persisted (no such field)
    # EXPIRED is system-only: no client transition, rejected as invalid state.
    if to_state not in CERT_FROM or cert["status"] not in CERT_FROM[to_state]:
        err_invalid_state("certificate cannot transition from %s to %s" % (cert["status"], to_state))
    if to_state == "ACTIVE":
        if now() >= cert["expires_at"]:
            raise_err("ERR_CERTIFICATE_EXPIRED", 422, "certificate has reached expires_at")
        cert["status"] = "ACTIVE"
        touch(cert)
    elif to_state == "SUSPENDED":
        cert["status"] = "SUSPENDED"
        touch(cert)
    else:  # REVOKED
        revoke_cascade(cert)
        cert["status"] = "REVOKED"
        touch(cert)
    return ok_object(cert, 200)
