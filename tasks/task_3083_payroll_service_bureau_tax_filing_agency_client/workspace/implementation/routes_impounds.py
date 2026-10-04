"""Impound and FundingFailureEvent endpoints."""

from flask import Blueprint, request

import errors
from db import store
from middleware import authenticate, require_roles, check_client_identity
from response import success_object, success_list
from services_common import paginate, touch, now_iso, public
from services_strikes import apply_funding_strike, cancel_scheduled_deposits_for_run, resolve_funding_failure

bp = Blueprint("impounds", __name__)

READ_ROLES = {"BureauCompliance", "BureauTreasury", "ClientPayrollAdmin"}


def imp_view(i):
    return public(i)


def _get_impound(impound_id):
    i = store.impounds.get(impound_id)
    if not i:
        raise errors.not_found("Impound not found")
    return i


@bp.route("/impounds", methods=["GET"])
def list_impounds():
    auth = authenticate()
    require_roles(auth, READ_ROLES)
    items = list(store.impounds.values())
    if auth.role == "ClientPayrollAdmin":
        items = [i for i in items if i["client_id"] == auth.user_id]
    prid = request.args.get("payroll_run_id")
    if prid is not None:
        items = [i for i in items if i["payroll_run_id"] == prid]
    cid = request.args.get("client_id")
    if cid is not None:
        items = [i for i in items if i["client_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([imp_view(i) for i in page], limit, offset, total)


@bp.route("/impounds/<impoundId>", methods=["GET"])
def get_impound(impoundId):
    auth = authenticate()
    require_roles(auth, READ_ROLES)
    i = _get_impound(impoundId)
    check_client_identity(auth, i["client_id"])
    return success_object(imp_view(i))


@bp.route("/impounds/<impoundId>/settle", methods=["POST"])
def settle_impound(impoundId):
    auth = authenticate()
    require_roles(auth, {"BureauTreasury"})
    imp = _get_impound(impoundId)
    if imp["status"] != "PENDING":
        raise errors.invalid_state("Impound must be PENDING to settle")
    run = store.payroll_runs[imp["payroll_run_id"]]
    if run["funding_model"] == "WIRE_REQUIRED" and not run.get("funding_confirmed_at"):
        raise errors.wire_confirmation_required("Wire confirmation required before settlement")
    imp["status"] = "SETTLED"
    imp["settled_at"] = now_iso()
    touch(imp)
    run["status"] = "SETTLED"
    touch(run)
    return success_object(imp_view(imp))


@bp.route("/impounds/<impoundId>/fail", methods=["POST"])
def fail_impound(impoundId):
    auth = authenticate()
    require_roles(auth, {"BureauTreasury"})
    imp = _get_impound(impoundId)
    if imp["status"] != "PENDING":
        raise errors.invalid_state("Impound must be PENDING to fail")
    imp["status"] = "FAILED"
    touch(imp)
    run = store.payroll_runs[imp["payroll_run_id"]]
    run["status"] = "REVERSED"
    touch(run)
    client = store.clients[imp["client_id"]]
    apply_funding_strike(client, imp, "NSF_RETURN")
    cancel_scheduled_deposits_for_run(run["id"])
    return success_object(imp_view(imp))


@bp.route("/impounds/<impoundId>/return", methods=["POST"])
def return_impound(impoundId):
    auth = authenticate()
    require_roles(auth, {"BureauTreasury"})
    imp = _get_impound(impoundId)
    if imp["status"] != "SETTLED":
        raise errors.invalid_state("Impound must be SETTLED to return")
    imp["status"] = "RETURNED"
    touch(imp)
    client = store.clients[imp["client_id"]]
    apply_funding_strike(client, imp, "NSF_RETURN")
    return success_object(imp_view(imp))


@bp.route("/impounds/<impoundId>/confirm-wire", methods=["POST"])
def confirm_wire(impoundId):
    auth = authenticate()
    require_roles(auth, {"ClientPayrollAdmin"})
    imp = _get_impound(impoundId)
    check_client_identity(auth, imp["client_id"])
    run = store.payroll_runs[imp["payroll_run_id"]]
    if run["funding_model"] != "WIRE_REQUIRED":
        raise errors.invalid_state("Run is not WIRE_REQUIRED")
    if imp["status"] != "PENDING":
        raise errors.invalid_state("Impound must be PENDING to confirm wire")
    run["funding_confirmed_at"] = now_iso()
    touch(run)
    return success_object(imp_view(imp))


@bp.route("/impounds/<impoundId>/miss-wire", methods=["POST"])
def miss_wire(impoundId):
    auth = authenticate()
    require_roles(auth, {"BureauTreasury"})
    imp = _get_impound(impoundId)
    run = store.payroll_runs[imp["payroll_run_id"]]
    if run["funding_model"] != "WIRE_REQUIRED":
        raise errors.invalid_state("Run is not WIRE_REQUIRED")
    if imp["status"] != "PENDING":
        raise errors.invalid_state("Impound must be PENDING to record missed wire")
    imp["status"] = "FAILED"
    touch(imp)
    run["status"] = "REVERSED"
    touch(run)
    client = store.clients[imp["client_id"]]
    apply_funding_strike(client, imp, "WIRE_NOT_CONFIRMED")
    cancel_scheduled_deposits_for_run(run["id"])
    return success_object(imp_view(imp))


# --- FundingFailureEvent endpoints ---

FF_ROLES = {"BureauCompliance", "BureauTreasury"}


@bp.route("/funding-failures", methods=["GET"])
def list_funding_failures():
    auth = authenticate()
    require_roles(auth, FF_ROLES)
    items = list(store.funding_failures.values())
    iid = request.args.get("impound_id")
    if iid is not None:
        items = [e for e in items if e["impound_id"] == iid]
    cid = request.args.get("client_id")
    if cid is not None:
        items = [e for e in items if e["client_id"] == cid]
    resolved = request.args.get("resolved")
    if resolved is not None:
        val = resolved.lower() == "true"
        items = [e for e in items if (e.get("resolved_at") is not None) == val]
    page, limit, offset, total = paginate(items)
    return success_list([public(e) for e in page], limit, offset, total)


@bp.route("/funding-failures/<eventId>", methods=["GET"])
def get_funding_failure(eventId):
    auth = authenticate()
    require_roles(auth, FF_ROLES)
    e = store.funding_failures.get(eventId)
    if not e:
        raise errors.not_found("Funding failure event not found")
    return success_object(public(e))


@bp.route("/funding-failures/<eventId>/resolve", methods=["POST"])
def resolve_event(eventId):
    auth = authenticate()
    require_roles(auth, {"BureauTreasury"})
    e = store.funding_failures.get(eventId)
    if not e:
        raise errors.not_found("Funding failure event not found")
    if e.get("resolved_at") is not None:
        raise errors.invalid_state("Funding failure already resolved")
    client = store.clients[e["client_id"]]
    resolve_funding_failure(client, e)
    return success_object(public(e))
