import secrets
import string
from datetime import timedelta

import db
import clock
import engine
from util import fmt_iso, parse_iso, hash_token
from services import transfer_view
from middleware import require_roles, body_json, require_fields, pagination_params
from response import success_object, success_list
from errors import (
    err_invalid_request, err_not_found, err_invalid_state, ApiError,
)
from flask import Blueprint, request

bp = Blueprint("transfers", __name__)


def _get_transfer_or_404(tid):
    t = db.transfers.get(tid)
    if t is None:
        raise err_not_found()
    return t


def _new_auth_code():
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(24))


@bp.post("/transfers")
def create_transfer():
    role, user_id = require_roles("RegistrarOperator")
    data = body_json()
    require_fields(data, ["domain_id", "to_registrar_id"])
    did = data["domain_id"]
    if not isinstance(did, str):
        raise err_invalid_request("domain_id must be a string")
    d = db.domains.get(did)
    if d is None:
        raise err_not_found("domain_id does not exist")
    to_rid = data["to_registrar_id"]
    if not isinstance(to_rid, str):
        raise err_invalid_request("to_registrar_id must be a string")
    gaining = db.registrars.get(to_rid)
    if gaining is None:
        raise err_not_found("to_registrar_id does not exist")
    for t in db.transfers.values():
        if t["domain_id"] == d["id"] and t["status"] == "DISPUTED":
            raise ApiError("ERR_TRANSFER_DISPUTED", "Domain has a DISPUTED transfer", 409)
    for t in db.transfers.values():
        if t["domain_id"] == d["id"] and t["status"] == "REQUESTED":
            raise ApiError("ERR_TRANSFER_ALREADY_PENDING",
                           "Another transfer for this domain is REQUESTED", 409)
    if d["status"] != "ACTIVE":
        raise err_invalid_state()
    if d["suspension_status"] != "NONE":
        raise ApiError("ERR_DOMAIN_SUSPENDED", "Domain suspension blocks transfer requests", 409)
    if d["lock_status"] != "NONE":
        raise ApiError("ERR_DOMAIN_LOCKED", "Domain lock blocks transfer requests", 409)
    now = clock.now()
    if now < parse_iso(d["created_at"]) + timedelta(days=60):
        raise ApiError("ERR_TRANSFER_WINDOW_CLOSED", "Domain is younger than 60 days", 409)
    if gaining["status"] != "ACTIVE":
        raise ApiError("ERR_REGISTRAR_NOT_ACTIVE", "Gaining registrar is not ACTIVE", 409)
    if gaining["credit_hold"]:
        raise ApiError("ERR_REGISTRAR_CREDIT_HOLD", "Gaining registrar credit hold", 409)
    auth_code = _new_auth_code()
    rec = db.new_common(now)
    rec.update({
        "domain_id": d["id"],
        "from_registrar_id": d["registrar_id"],
        "to_registrar_id": to_rid,
        "auth_code_hash": hash_token(auth_code),
        "auth_code_expires_at": fmt_iso(now + timedelta(days=14)),
        "requested_at": fmt_iso(now),
        "status": "REQUESTED",
        "dispute_reason": None,
        "_plaintext_auth_code": auth_code,
        "_completed_at": None,
    })
    db.transfers[rec["id"]] = rec
    d["status"] = "TRANSFERRING"
    db.touch(d, now)
    return success_object(transfer_view(rec, include_auth_code=True), 201)


@bp.get("/transfers")
def list_transfers():
    require_roles("RegistryAdmin", "RegistrarOperator")
    limit, offset = pagination_params()
    rows = sorted(db.transfers.values(), key=lambda t: t["created_at"])
    for key in ("domain_id", "from_registrar_id", "to_registrar_id", "status"):
        v = request.args.get(key)
        if v:
            rows = [t for t in rows if t[key] == v]
    total = len(rows)
    page = rows[offset:offset + limit]
    return success_list([transfer_view(t) for t in page], limit, offset, total)


@bp.get("/transfers/<tid>")
def get_transfer(tid):
    require_roles("RegistryAdmin", "RegistrarOperator")
    t = _get_transfer_or_404(tid)
    return success_object(transfer_view(t))


@bp.post("/transfers/<tid>/ack")
def ack_transfer(tid):
    role, user_id = require_roles("RegistrarOperator")
    t = _get_transfer_or_404(tid)
    if user_id != t["from_registrar_id"]:
        raise ApiError("ERR_NOT_TRANSFER_PARTY", "Acting registrar is not the losing party", 403)
    data = body_json()
    require_fields(data, ["auth_code"])
    now = clock.now()
    if now > parse_iso(t["auth_code_expires_at"]):
        raise ApiError("ERR_AUTH_CODE_EXPIRED", "Auth code expired", 409)
    if hash_token(str(data["auth_code"])) != t["auth_code_hash"]:
        raise ApiError("ERR_AUTH_CODE_INVALID", "Submitted auth_code does not match", 409)
    if t["status"] != "REQUESTED":
        raise err_invalid_state()
    t["status"] = "ACKED"
    db.touch(t, now)
    return success_object(transfer_view(t))


@bp.post("/transfers/<tid>/nack")
def nack_transfer(tid):
    role, user_id = require_roles("RegistrarOperator")
    t = _get_transfer_or_404(tid)
    if t["status"] != "REQUESTED":
        raise err_invalid_state()
    if user_id != t["from_registrar_id"]:
        raise ApiError("ERR_NOT_TRANSFER_PARTY", "Acting registrar is not the losing party", 403)
    t["status"] = "NACKED"
    db.touch(t, clock.now())
    d = db.domains.get(t["domain_id"])
    if d is not None and d["status"] == "TRANSFERRING":
        d["status"] = "ACTIVE"
        db.touch(d, clock.now())
    return success_object(transfer_view(t))


@bp.post("/transfers/<tid>/complete")
def complete_transfer(tid):
    role, user_id = require_roles("RegistrarOperator")
    t = _get_transfer_or_404(tid)
    if t["status"] not in ("ACKED", "AUTO_ACKED"):
        raise err_invalid_state()
    if user_id != t["to_registrar_id"]:
        raise ApiError("ERR_NOT_TRANSFER_PARTY", "Acting registrar is not the gaining party", 403)
    now = clock.now()
    t["status"] = "COMPLETED"
    t["_completed_at"] = fmt_iso(now)
    db.touch(t, now)
    engine._complete_transfer_side_effects(t)
    return success_object(transfer_view(t))


@bp.post("/transfers/<tid>/dispute")
def dispute_transfer(tid):
    role, user_id = require_roles("RegistrarOperator")
    t = _get_transfer_or_404(tid)
    if t["status"] != "COMPLETED":
        raise err_invalid_state()
    if user_id != t["from_registrar_id"]:
        raise ApiError("ERR_NOT_TRANSFER_PARTY", "Acting registrar is not the losing party", 403)
    data = body_json()
    require_fields(data, ["dispute_reason"])
    if not isinstance(data["dispute_reason"], str) or not data["dispute_reason"]:
        raise err_invalid_request("dispute_reason must be a non-empty string")
    now = clock.now()
    completed = parse_iso(t["_completed_at"])
    if now > completed + timedelta(days=183):  # 6 months
        raise ApiError("ERR_DISPUTE_WINDOW_CLOSED", "Dispute attempted after 6 months", 409)
    t["status"] = "DISPUTED"
    t["dispute_reason"] = data["dispute_reason"]
    db.touch(t, now)
    return success_object(transfer_view(t))


@bp.post("/transfers/<tid>/reverse")
def reverse_transfer(tid):
    require_roles("RegistryAdmin")
    t = _get_transfer_or_404(tid)
    if t["status"] != "DISPUTED":
        raise err_invalid_state()
    data = body_json()
    uphold = data.get("uphold", False)
    if uphold is True:
        t["status"] = "COMPLETED"
        db.touch(t, clock.now())
        return success_object(transfer_view(t))
    now = clock.now()
    t["status"] = "REVERSED"
    db.touch(t, now)
    d = db.domains.get(t["domain_id"])
    if d is not None:
        from util import add_years
        from services import AUTO_RENEW_GRACE_DAYS
        d["registrar_id"] = t["from_registrar_id"]
        new_expiry = add_years(parse_iso(d["expires_on"]), -1)
        d["expires_on"] = fmt_iso(new_expiry)
        d["grace_deadline"] = fmt_iso(new_expiry + timedelta(days=AUTO_RENEW_GRACE_DAYS))
        db.touch(d, now)
    # void the TRANSFER invoice
    import fiscal
    for inv in db.invoices.values():
        if inv["domain_id"] == t["domain_id"] and inv["kind"] == "TRANSFER" \
                and inv["registrar_id"] == t["to_registrar_id"] and inv["status"] == "OPEN":
            fiscal.void_invoice(inv)
    return success_object(transfer_view(t))
