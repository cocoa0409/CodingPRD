"""AgencyNotice endpoints."""

from flask import Blueprint, request

import errors
from db import store
from middleware import authenticate, require_roles, check_client_identity
from response import success_object, success_list
from services_common import new_entity, paginate, touch, parse_datetime, public

bp = Blueprint("notices", __name__)

READ_ROLES = {"BureauCompliance", "BureauTaxFiler", "ClientPayrollAdmin"}
NOTICE_TYPES = {"BALANCE_DUE", "PENALTY_ASSESSMENT", "DATA_MISMATCH", "MISSING_RETURN"}


def _get_notice(notice_id):
    n = store.notices.get(notice_id)
    if not n:
        raise errors.not_found("Notice not found")
    return n


@bp.route("/notices", methods=["POST"])
def create_notice():
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler", "BureauCompliance"})
    body = request.get_json(silent=True) or {}

    client_id = body.get("client_id")
    if not client_id:
        raise errors.invalid_request("client_id is required")
    if client_id not in store.clients:
        raise errors.not_found("Client not found")

    jurisdiction_id = body.get("jurisdiction_id")
    if not jurisdiction_id:
        raise errors.invalid_request("jurisdiction_id is required")
    if jurisdiction_id not in store.jurisdictions:
        raise errors.not_found("Jurisdiction not found")

    return_id = body.get("return_id")
    if not return_id:
        raise errors.invalid_request("return_id is required")
    if return_id not in store.returns:
        raise errors.not_found("Return not found")

    notice_type = body.get("notice_type")
    if not notice_type:
        raise errors.invalid_request("notice_type is required")
    if notice_type not in NOTICE_TYPES:
        raise errors.invalid_request("notice_type out of domain")

    claimed = body.get("claimed_amount_cents")
    if claimed is None:
        raise errors.invalid_request("claimed_amount_cents is required")
    if not isinstance(claimed, int) or isinstance(claimed, bool) or claimed < 0:
        raise errors.invalid_request("claimed_amount_cents must be a non-negative integer")

    received_at = body.get("received_at")
    response_due_at = body.get("response_due_at")
    if not received_at or not response_due_at:
        raise errors.invalid_request("received_at and response_due_at are required")
    if parse_datetime(received_at) is None or parse_datetime(response_due_at) is None:
        raise errors.invalid_request("Invalid datetime format")

    n = new_entity({
        "client_id": client_id,
        "jurisdiction_id": jurisdiction_id,
        "return_id": return_id,
        "notice_type": notice_type,
        "claimed_amount_cents": claimed,
        "received_at": received_at,
        "response_due_at": response_due_at,
        "status": "OPEN",
        "resolution_note": None,
        "adjustment_amount_cents": 0,
    })
    store.notices[n["id"]] = n
    return success_object(public(n), status=201)


@bp.route("/notices", methods=["GET"])
def list_notices():
    auth = authenticate()
    require_roles(auth, READ_ROLES)
    items = list(store.notices.values())
    if auth.role == "ClientPayrollAdmin":
        items = [n for n in items if n["client_id"] == auth.user_id]
    cid = request.args.get("client_id")
    if cid is not None:
        items = [n for n in items if n["client_id"] == cid]
    jid = request.args.get("jurisdiction_id")
    if jid is not None:
        items = [n for n in items if n["jurisdiction_id"] == jid]
    rid = request.args.get("return_id")
    if rid is not None:
        items = [n for n in items if n["return_id"] == rid]
    status = request.args.get("status")
    if status is not None:
        items = [n for n in items if n["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([public(n) for n in page], limit, offset, total)


@bp.route("/notices/<noticeId>", methods=["GET"])
def get_notice(noticeId):
    auth = authenticate()
    require_roles(auth, READ_ROLES)
    n = _get_notice(noticeId)
    check_client_identity(auth, n["client_id"])
    return success_object(public(n))


@bp.route("/notices/<noticeId>/start-review", methods=["POST"])
def start_review(noticeId):
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    n = _get_notice(noticeId)
    if n["status"] not in ("OPEN", "ESCALATED"):
        raise errors.invalid_state("Notice must be OPEN or ESCALATED to start review")
    n["status"] = "IN_REVIEW"
    touch(n)
    return success_object(public(n))


@bp.route("/notices/<noticeId>/resolve", methods=["POST"])
def resolve_notice(noticeId):
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    n = _get_notice(noticeId)
    if n["status"] != "IN_REVIEW":
        raise errors.invalid_state("Notice must be IN_REVIEW to resolve")
    body = request.get_json(silent=True) or {}
    resolution = body.get("resolution")
    if resolution not in ("NO_CHANGE", "ADJUSTMENT"):
        raise errors.invalid_request("resolution must be NO_CHANGE or ADJUSTMENT")
    resolution_note = body.get("resolution_note")
    if resolution == "NO_CHANGE":
        n["status"] = "RESOLVED_NO_CHANGE"
        n["adjustment_amount_cents"] = 0
    else:
        adj = body.get("adjustment_amount_cents")
        if adj is None or not isinstance(adj, int) or isinstance(adj, bool) or adj <= 0:
            raise errors.invalid_request("adjustment_amount_cents must be supplied and > 0")
        n["status"] = "RESOLVED_ADJUSTMENT"
        n["adjustment_amount_cents"] = adj
    n["resolution_note"] = resolution_note
    touch(n)
    return success_object(public(n))


@bp.route("/notices/<noticeId>/escalate", methods=["POST"])
def escalate_notice(noticeId):
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    n = _get_notice(noticeId)
    if n["status"] != "IN_REVIEW":
        raise errors.invalid_state("Notice must be IN_REVIEW to escalate")
    n["status"] = "ESCALATED"
    touch(n)
    return success_object(public(n))


@bp.route("/notices/<noticeId>/close", methods=["POST"])
def close_notice(noticeId):
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    n = _get_notice(noticeId)
    if n["status"] not in ("RESOLVED_NO_CHANGE", "RESOLVED_ADJUSTMENT"):
        raise errors.invalid_state("Notice must be RESOLVED to close")
    n["status"] = "CLOSED"
    touch(n)
    return success_object(public(n))
