"""ReturnAmendment endpoints."""

from flask import Blueprint, request

import errors
from db import store
from middleware import authenticate, require_roles, check_client_identity
from response import success_object, success_list
from services_common import new_entity, paginate, touch, now_iso, public

bp = Blueprint("amendments", __name__)

READ_ROLES = {"BureauCompliance", "BureauTaxFiler", "ClientPayrollAdmin"}


def _get_amendment(amendment_id):
    a = store.amendments.get(amendment_id)
    if not a:
        raise errors.not_found("Amendment not found")
    return a


@bp.route("/amendments", methods=["POST"])
def create_amendment():
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    body = request.get_json(silent=True) or {}
    return_id = body.get("return_id")
    if not return_id:
        raise errors.invalid_request("return_id is required")
    ret = store.returns.get(return_id)
    if not ret:
        raise errors.not_found("Return not found")
    if body.get("reason") is None:
        raise errors.invalid_request("reason is required")
    adjusted = body.get("adjusted_liability_cents")
    if adjusted is None:
        raise errors.invalid_request("adjusted_liability_cents is required")
    if not isinstance(adjusted, int) or isinstance(adjusted, bool) or adjusted < 0:
        raise errors.invalid_request("adjusted_liability_cents must be a non-negative integer")
    if ret["status"] not in ("ACCEPTED", "RECONCILED"):
        raise errors.return_not_amendable("Return is not ACCEPTED or RECONCILED")
    a = new_entity({
        "return_id": return_id,
        "reason": body["reason"],
        "adjusted_liability_cents": adjusted,
        "status": "DRAFT",
        "_filed_by": None,
    })
    store.amendments[a["id"]] = a
    return success_object(public(a), status=201)


@bp.route("/amendments", methods=["GET"])
def list_amendments():
    auth = authenticate()
    require_roles(auth, READ_ROLES)
    items = list(store.amendments.values())
    rid = request.args.get("return_id")
    if rid is not None:
        items = [a for a in items if a["return_id"] == rid]
    status = request.args.get("status")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if auth.role == "ClientPayrollAdmin":
        items = [a for a in items
                 if store.returns.get(a["return_id"], {}).get("client_id") == auth.user_id]
    page, limit, offset, total = paginate(items)
    return success_list([public(a) for a in page], limit, offset, total)


@bp.route("/amendments/<amendmentId>", methods=["GET"])
def get_amendment(amendmentId):
    auth = authenticate()
    require_roles(auth, READ_ROLES)
    a = _get_amendment(amendmentId)
    ret = store.returns.get(a["return_id"])
    if ret:
        check_client_identity(auth, ret["client_id"])
    return success_object(public(a))


@bp.route("/amendments/<amendmentId>/file", methods=["POST"])
def file_amendment(amendmentId):
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    a = _get_amendment(amendmentId)
    if a["status"] != "DRAFT":
        raise errors.invalid_state("Amendment must be DRAFT to file")
    ret = store.returns[a["return_id"]]
    if ret["status"] not in ("ACCEPTED", "RECONCILED"):
        raise errors.return_not_amendable("Amended return is not ACCEPTED or RECONCILED")
    a["status"] = "FILED"
    a["_filed_by"] = auth.user_id
    touch(a)
    return success_object(public(a))


def _sod_check(auth, amendment):
    if amendment.get("_filed_by") is not None and amendment["_filed_by"] == auth.user_id:
        raise errors.sod_violation("The filer cannot perform this action")


@bp.route("/amendments/<amendmentId>/accept", methods=["POST"])
def accept_amendment(amendmentId):
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    a = _get_amendment(amendmentId)
    if a["status"] != "FILED":
        raise errors.invalid_state("Amendment must be FILED to accept")
    _sod_check(auth, a)
    a["status"] = "ACCEPTED"
    touch(a)
    # Supersession: amended return -> AMENDED; new FILED return created
    ret = store.returns[a["return_id"]]
    ret["status"] = "AMENDED"
    touch(ret)
    new_ret = new_entity({
        "client_id": ret["client_id"],
        "jurisdiction_id": ret["jurisdiction_id"],
        "period": ret["period"],
        "filing_method": ret["filing_method"],
        "status": "FILED",
        "expected_liability_cents": a["adjusted_liability_cents"],
        "filed_at": now_iso(),
        "reconciled_at": None,
        "supersedes_return_id": ret["id"],
        "shortfall_penalty_exposure_cents": 0,
        "_filed_by": None,
    })
    store.returns[new_ret["id"]] = new_ret
    return success_object(public(a))


@bp.route("/amendments/<amendmentId>/reject", methods=["POST"])
def reject_amendment(amendmentId):
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    a = _get_amendment(amendmentId)
    if a["status"] != "FILED":
        raise errors.invalid_state("Amendment must be FILED to reject")
    _sod_check(auth, a)
    a["status"] = "REJECTED"
    touch(a)
    return success_object(public(a))


@bp.route("/amendments/<amendmentId>/redraft", methods=["POST"])
def redraft_amendment(amendmentId):
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    a = _get_amendment(amendmentId)
    if a["status"] != "REJECTED":
        raise errors.invalid_state("Amendment must be REJECTED to redraft")
    a["status"] = "DRAFT"
    touch(a)
    return success_object(public(a))
