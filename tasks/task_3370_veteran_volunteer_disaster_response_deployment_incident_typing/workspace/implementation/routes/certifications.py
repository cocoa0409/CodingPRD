"""Certification endpoints: record, list, get, verify/reject/renew/revoke."""
from flask import Blueprint
import db
import errors
import envelope
import validation as V
import auth
import domain
import cascades
import timeutil
from constants import CERT_KINDS, CERT_STATUSES

bp = Blueprint("certifications", __name__)

CERT_READ_ROLES = ("SystemAdmin", "SafetyOfficer", "TrainingDirector",
                   "OperationsLead", "IncidentCommander", "Volunteer")


@bp.post("/vdr/volunteers/<vid>/certifications")
def create_certification(vid):
    body = V.get_body()
    V.check_unknown(body, {"kind", "issued_at", "expires_at"})
    kind = V.req_enum(body, "kind", CERT_KINDS)
    issued_at = V.req_dt(body, "issued_at")
    expires_at = V.req_dt(body, "expires_at")
    auth.require_roles("TrainingDirector")
    vol = db.get("volunteers", vid)
    if vol is None:
        errors.volunteer_not_found()
    cert = db.mint("certifications", {
        "volunteer_id": vid,
        "kind": kind,
        "status": "PENDING_VERIFICATION",
        "issued_at": timeutil.fmt(issued_at),
        "expires_at": timeutil.fmt(expires_at),
        "verified_by_user_id": None,
        "renewal_count": 0,
    })
    return envelope.ok(domain.public(cert), 201)


def _qparam(name):
    from flask import request
    v = request.args.get(name)
    return v if v not in (None, "") else None


@bp.get("/vdr/certifications")
def list_certifications():
    auth.require_roles(*CERT_READ_ROLES)
    items = db.all_of("certifications")
    volunteer_id = _qparam("volunteer_id")
    status = _qparam("status")
    if volunteer_id is not None:
        items = [c for c in items if c["volunteer_id"] == volunteer_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return envelope.paginate(domain.public_list(items))


@bp.get("/vdr/certifications/<cid>")
def get_certification(cid):
    uid, role = auth.require_roles(*CERT_READ_ROLES)
    cert = db.get("certifications", cid)
    if cert is None:
        errors.certification_not_found()
    if role == "Volunteer" and cert["volunteer_id"] != uid:
        errors.unauthorized("a Volunteer may only read their own certifications")
    return envelope.ok(domain.public(cert))


@bp.patch("/vdr/certifications/<cid>")
def patch_certification(cid):
    body = V.get_body()
    V.check_unknown(body, {"status", "expires_at"})
    target = V.req_enum(body, "status", CERT_STATUSES)
    has_expiry = "expires_at" in body and body["expires_at"] is not None
    new_expiry = V.req_dt(body, "expires_at") if has_expiry else None
    uid, role = auth.require_roles("SafetyOfficer")
    cert = db.get("certifications", cid)
    if cert is None:
        errors.certification_not_found()
    cur = cert["status"]
    now = db.now()

    if target == "VERIFIED" and cur == "PENDING_VERIFICATION":
        if now > timeutil.parse_iso(cert["expires_at"]):
            errors.err("ERR_CERT_NOT_VERIFIED", 422,
                       "credential is already past its expires_at")
        cert["status"] = "VERIFIED"
        cert["verified_by_user_id"] = uid
        db.touch(cert)
    elif target == "REJECTED" and cur == "PENDING_VERIFICATION":
        cert["status"] = "REJECTED"
        db.touch(cert)
    elif target == "VERIFIED" and cur == "EXPIRED":
        # Renewal: requires a new expires_at strictly greater than current_utc.
        if new_expiry is None:
            errors.validation("renewal requires a new expires_at")
        if new_expiry <= now:
            errors.err("ERR_CERT_NOT_VERIFIED", 422,
                       "new expires_at must be strictly later than current_utc")
        cert["status"] = "VERIFIED"
        cert["expires_at"] = timeutil.fmt(new_expiry)
        cert["renewal_count"] += 1
        cert["verified_by_user_id"] = uid
        db.touch(cert)
    elif target == "REVOKED" and cur == "VERIFIED":
        cert["status"] = "REVOKED"
        db.touch(cert)
        cascades.revoke_cascade(cert)
    else:
        errors.invalid_state(
            "cannot transition certification from %s to %s" % (cur, target))

    owner = db.get("volunteers", cert["volunteer_id"])
    if owner is not None:
        domain.recompute_readiness(owner)
        db.touch(owner)
    return envelope.ok(domain.public(cert))
