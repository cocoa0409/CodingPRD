"""Client endpoints: lifecycle, credit hold, funding failures, credit assessments."""

from flask import Blueprint, request

import errors
from db import store
from middleware import authenticate, require_roles, check_client_identity
from response import success_object, success_list
from services_common import new_entity, paginate, touch, now_iso, public
from services_calc import recompute_risk_posture

bp = Blueprint("clients", __name__)

BUREAU_READERS = {"BureauCompliance", "BureauOnboarder", "BureauTaxFiler", "BureauTreasury"}


def client_view(c):
    return public(c)


def _get_client(client_id):
    c = store.clients.get(client_id)
    if not c:
        raise errors.not_found("Client not found")
    return c


@bp.route("/clients", methods=["POST"])
def create_client():
    auth = authenticate()
    require_roles(auth, {"BureauOnboarder"})
    body = request.get_json(silent=True) or {}
    if not body.get("legal_name"):
        raise errors.invalid_request("legal_name is required")
    if not body.get("ein"):
        raise errors.invalid_request("ein is required")
    # EIN unique among non-terminated clients
    for c in store.clients.values():
        if c["ein"] == body["ein"] and c["status"] != "TERMINATED":
            raise errors.invalid_request("ein must be unique among non-terminated clients")
    c = new_entity({
        "legal_name": body["legal_name"],
        "ein": body["ein"],
        "status": "PROSPECT",
        "risk_posture": "NORMAL",
        "funding_failure_count": 0,
        "credit_hold": False,
        "onboarded_at": None,
    })
    store.clients[c["id"]] = c
    return success_object(client_view(c), status=201)


@bp.route("/clients", methods=["GET"])
def list_clients():
    auth = authenticate()
    require_roles(auth, BUREAU_READERS)
    items = list(store.clients.values())
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    posture = request.args.get("risk_posture")
    if posture is not None:
        items = [c for c in items if c["risk_posture"] == posture]
    page, limit, offset, total = paginate(items)
    return success_list([client_view(c) for c in page], limit, offset, total)


@bp.route("/clients/<clientId>", methods=["GET"])
def get_client(clientId):
    auth = authenticate()
    require_roles(auth, BUREAU_READERS | {"ClientPayrollAdmin"})
    c = _get_client(clientId)
    check_client_identity(auth, clientId)
    return success_object(client_view(c))


@bp.route("/clients/<clientId>/begin-onboarding", methods=["POST"])
def begin_onboarding(clientId):
    auth = authenticate()
    require_roles(auth, {"BureauOnboarder"})
    c = _get_client(clientId)
    if c["status"] != "PROSPECT":
        raise errors.invalid_state("Client must be PROSPECT to begin onboarding")
    c["status"] = "ONBOARDING"
    touch(c)
    return success_object(client_view(c))


@bp.route("/clients/<clientId>/activate", methods=["POST"])
def activate_client(clientId):
    auth = authenticate()
    require_roles(auth, {"BureauOnboarder"})
    c = _get_client(clientId)
    if c["status"] != "ONBOARDING":
        raise errors.invalid_state("Client must be ONBOARDING to activate")
    # Business rules: credit hold first (priority 9), then verified jurisdiction (priority 22)
    if c["credit_hold"]:
        raise errors.credit_hold_active("Credit hold blocks activation")
    has_verified = any(
        r["client_id"] == clientId and r["status"] == "VERIFIED"
        for r in store.registrations.values()
    )
    if not has_verified:
        raise errors.no_verified_jurisdiction("At least one VERIFIED registration is required")
    c["status"] = "ACTIVE"
    c["onboarded_at"] = now_iso()
    touch(c)
    return success_object(client_view(c))


@bp.route("/clients/<clientId>/terminate", methods=["POST"])
def terminate_client(clientId):
    auth = authenticate()
    require_roles(auth, {"BureauCompliance"})
    c = _get_client(clientId)
    if c["status"] not in ("ACTIVE", "SUSPENDED"):
        raise errors.invalid_state("Client must be ACTIVE or SUSPENDED to terminate")
    # Open obligation sweep
    for imp in store.impounds.values():
        if imp["client_id"] == clientId and imp["status"] == "PENDING":
            raise errors.pending_impounds("Client has a PENDING impound")
    for dep in store.deposits.values():
        if dep["client_id"] == clientId and dep["status"] in ("SCHEDULED", "SUBMITTED"):
            raise errors.open_obligations("Client has open deposits")
    for n in store.notices.values():
        if n["client_id"] == clientId and n["status"] in ("OPEN", "IN_REVIEW"):
            raise errors.open_obligations("Client has open notices")
    for run in store.payroll_runs.values():
        if run["client_id"] == clientId and run["status"] in ("DRAFT", "SUBMITTED", "IMPOUNDED"):
            raise errors.open_obligations("Client has non-terminal payroll runs")
    c["status"] = "TERMINATED"
    touch(c)
    return success_object(client_view(c))


@bp.route("/clients/<clientId>/reactivate", methods=["POST"])
def reactivate_client(clientId):
    auth = authenticate()
    require_roles(auth, {"BureauCompliance"})
    c = _get_client(clientId)
    if c["status"] != "SUSPENDED":
        raise errors.invalid_state("Client must be SUSPENDED to reactivate")
    # credit hold (priority 9) then unresolved failures (priority 23)
    if c["credit_hold"]:
        raise errors.credit_hold_active("Credit hold blocks reactivation")
    unresolved = [e for e in store.funding_failures.values()
                  if e["client_id"] == clientId and e.get("resolved_at") is None]
    if unresolved:
        raise errors.unresolved_funding_failures("Unresolved funding failures remain")
    c["status"] = "ACTIVE"
    recompute_risk_posture(c)
    touch(c)
    return success_object(client_view(c))


@bp.route("/clients/<clientId>/credit-hold", methods=["POST"])
def set_credit_hold(clientId):
    auth = authenticate()
    require_roles(auth, {"BureauCompliance"})
    c = _get_client(clientId)
    body = request.get_json(silent=True) or {}
    hold = body.get("hold")
    if not isinstance(hold, bool):
        raise errors.invalid_request("hold must be a boolean")
    c["credit_hold"] = hold
    touch(c)
    return success_object(client_view(c))


@bp.route("/clients/<clientId>/funding-failures", methods=["GET"])
def list_client_funding_failures(clientId):
    auth = authenticate()
    require_roles(auth, {"BureauCompliance", "BureauTreasury", "BureauOnboarder"})
    _get_client(clientId)
    items = [e for e in store.funding_failures.values() if e["client_id"] == clientId]
    resolved = request.args.get("resolved")
    if resolved is not None:
        val = resolved.lower() == "true"
        items = [e for e in items if (e.get("resolved_at") is not None) == val]
    page, limit, offset, total = paginate(items)
    return success_list([public(e) for e in page], limit, offset, total)


@bp.route("/clients/<clientId>/credit-assessments", methods=["GET"])
def list_client_credit_assessments(clientId):
    auth = authenticate()
    require_roles(auth, {"BureauCompliance", "BureauTreasury"})
    _get_client(clientId)
    items = [a for a in store.credit_assessments.values() if a["client_id"] == clientId]
    page, limit, offset, total = paginate(items)
    return success_list([public(a) for a in page], limit, offset, total)


@bp.route("/clients/<clientId>/credit-assessments", methods=["POST"])
def create_credit_assessment(clientId):
    auth = authenticate()
    require_roles(auth, {"BureauCompliance"})
    c = _get_client(clientId)
    body = request.get_json(silent=True) or {}
    note = body.get("note")
    if not note:
        raise errors.invalid_request("note is required for MANUAL_REVIEW")
    prior = c["risk_posture"]
    new_posture, count = recompute_risk_posture(c)
    a = new_entity({
        "client_id": clientId,
        "assessed_at": now_iso(),
        "prior_posture": prior,
        "new_posture": new_posture,
        "trigger": "MANUAL_REVIEW",
        "note": note,
    })
    store.credit_assessments[a["id"]] = a
    touch(c)
    return success_object(public(a), status=201)
