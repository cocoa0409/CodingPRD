"""JurisdictionRegistration endpoints."""

from flask import Blueprint, request

import errors
from db import store
from middleware import authenticate, require_roles, check_client_identity
from response import success_object, success_list
from services_common import new_entity, paginate, touch, now_iso, public

bp = Blueprint("registrations", __name__)


def reg_view(r):
    return public(r)


@bp.route("/clients/<clientId>/registrations", methods=["POST"])
def create_registration(clientId):
    auth = authenticate()
    require_roles(auth, {"BureauOnboarder"})
    client = store.clients.get(clientId)
    if not client:
        raise errors.not_found("Client not found")
    body = request.get_json(silent=True) or {}
    jurisdiction_id = body.get("jurisdiction_id")
    if not jurisdiction_id:
        raise errors.invalid_request("jurisdiction_id is required")
    jur = store.jurisdictions.get(jurisdiction_id)
    if not jur:
        raise errors.not_found("Jurisdiction not found")
    if not jur.get("active", True):
        raise errors.invalid_request("Inactive jurisdiction cannot receive new registrations")
    r = new_entity({
        "client_id": clientId,
        "jurisdiction_id": jurisdiction_id,
        "agency_account_number": body.get("agency_account_number"),
        "poa_document_ref": body.get("poa_document_ref"),
        "status": "PENDING",
        "verified_at": None,
        "rejected_reason": None,
    })
    store.registrations[r["id"]] = r
    return success_object(reg_view(r), status=201)


@bp.route("/clients/<clientId>/registrations", methods=["GET"])
def list_client_registrations(clientId):
    auth = authenticate()
    require_roles(auth, {"BureauCompliance", "BureauOnboarder", "BureauTaxFiler", "ClientPayrollAdmin"})
    if clientId not in store.clients:
        raise errors.not_found("Client not found")
    check_client_identity(auth, clientId)
    items = [r for r in store.registrations.values() if r["client_id"] == clientId]
    jid = request.args.get("jurisdiction_id")
    if jid is not None:
        items = [r for r in items if r["jurisdiction_id"] == jid]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([reg_view(r) for r in page], limit, offset, total)


@bp.route("/registrations", methods=["GET"])
def list_registrations():
    auth = authenticate()
    require_roles(auth, {"BureauCompliance", "BureauOnboarder", "BureauTaxFiler"})
    items = list(store.registrations.values())
    cid = request.args.get("client_id")
    if cid is not None:
        items = [r for r in items if r["client_id"] == cid]
    jid = request.args.get("jurisdiction_id")
    if jid is not None:
        items = [r for r in items if r["jurisdiction_id"] == jid]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([reg_view(r) for r in page], limit, offset, total)


@bp.route("/registrations/<registrationId>", methods=["GET"])
def get_registration(registrationId):
    auth = authenticate()
    require_roles(auth, {"BureauCompliance", "BureauOnboarder", "BureauTaxFiler", "ClientPayrollAdmin"})
    r = store.registrations.get(registrationId)
    if not r:
        raise errors.not_found("Registration not found")
    check_client_identity(auth, r["client_id"])
    return success_object(reg_view(r))


@bp.route("/registrations/<registrationId>/verify", methods=["POST"])
def verify_registration(registrationId):
    auth = authenticate()
    require_roles(auth, {"BureauOnboarder"})
    r = store.registrations.get(registrationId)
    if not r:
        raise errors.not_found("Registration not found")
    if r["status"] != "PENDING":
        raise errors.invalid_state("Registration must be PENDING to verify")
    if not r.get("poa_document_ref") or not r.get("agency_account_number"):
        raise errors.poa_required("poa_document_ref and agency_account_number required")
    r["status"] = "VERIFIED"
    r["verified_at"] = now_iso()
    touch(r)
    return success_object(reg_view(r))


@bp.route("/registrations/<registrationId>/reject", methods=["POST"])
def reject_registration(registrationId):
    auth = authenticate()
    require_roles(auth, {"BureauOnboarder"})
    r = store.registrations.get(registrationId)
    if not r:
        raise errors.not_found("Registration not found")
    if r["status"] != "PENDING":
        raise errors.invalid_state("Registration must be PENDING to reject")
    body = request.get_json(silent=True) or {}
    r["status"] = "REJECTED"
    r["rejected_reason"] = body.get("reason")
    touch(r)
    return success_object(reg_view(r))


@bp.route("/registrations/<registrationId>/resubmit", methods=["POST"])
def resubmit_registration(registrationId):
    auth = authenticate()
    require_roles(auth, {"BureauOnboarder"})
    r = store.registrations.get(registrationId)
    if not r:
        raise errors.not_found("Registration not found")
    if r["status"] != "REJECTED":
        raise errors.invalid_state("Registration must be REJECTED to resubmit")
    r["status"] = "PENDING"
    r["verified_at"] = None
    r["rejected_reason"] = None
    touch(r)
    return success_object(reg_view(r))
