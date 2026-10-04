"""TaxReturn endpoints."""

from flask import Blueprint, request

import errors
from db import store
from middleware import authenticate, require_roles, check_client_identity
from response import success_object, success_list
from services_common import (
    public,
    new_entity, paginate, touch, now_iso, now_dt, parse_datetime, fmt_ts,
)
from services_calc import (
    bureau_books_liability, agency_confirmed_liability, shortfall_penalty,
    registration_for, period_bounds,
)

bp = Blueprint("returns", __name__)

READ_ROLES = {"BureauCompliance", "BureauTaxFiler", "ClientPayrollAdmin"}


def ret_view(r):
    out = public(r)
    # Bureau-books liability is re-derived on reads of FILED/ACCEPTED returns —
    # but not for amendment-created supersession filings, whose
    # expected_liability_cents is pinned to the amendment's
    # adjusted_liability_cents (PRD §3.8) and must not be recomputed.
    if r["status"] in ("FILED", "ACCEPTED") and not r.get("supersedes_return_id"):
        out["expected_liability_cents"] = bureau_books_liability(r["client_id"], r["period"])
    return out


def _get_return(return_id):
    r = store.returns.get(return_id)
    if not r:
        raise errors.not_found("Return not found")
    return r


@bp.route("/returns", methods=["POST"])
def create_return():
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    body = request.get_json(silent=True) or {}

    client_id = body.get("client_id")
    if not client_id:
        raise errors.invalid_request("client_id is required")
    client = store.clients.get(client_id)
    if not client:
        raise errors.not_found("Client not found")

    jurisdiction_id = body.get("jurisdiction_id")
    if not jurisdiction_id:
        raise errors.invalid_request("jurisdiction_id is required")
    jur = store.jurisdictions.get(jurisdiction_id)
    if not jur:
        raise errors.not_found("Jurisdiction not found")

    period = body.get("period")
    if not period:
        raise errors.invalid_request("period is required")
    expected = body.get("expected_client_version")
    if expected is None:
        raise errors.invalid_request("expected_client_version is required")
    if expected != client["version"]:
        raise errors.stale_version("expected_client_version does not match Client.version")

    # registration_interim_gate
    reg = registration_for(client_id, jurisdiction_id)
    if reg is None or reg["status"] == "REJECTED":
        raise errors.registration_not_verified("Registration is REJECTED or missing")
    filing_method = "ELECTRONIC" if reg["status"] == "VERIFIED" else "MANUAL_INTERIM"

    r = new_entity({
        "client_id": client_id,
        "jurisdiction_id": jurisdiction_id,
        "period": period,
        "filing_method": filing_method,
        "status": "DRAFT",
        "expected_liability_cents": 0,
        "filed_at": None,
        "reconciled_at": None,
        "supersedes_return_id": None,
        "shortfall_penalty_exposure_cents": 0,
        "_filed_by": None,
    })
    store.returns[r["id"]] = r
    touch(client)
    return success_object(ret_view(r), status=201)


@bp.route("/returns", methods=["GET"])
def list_returns():
    auth = authenticate()
    require_roles(auth, READ_ROLES)
    items = list(store.returns.values())
    if auth.role == "ClientPayrollAdmin":
        items = [r for r in items if r["client_id"] == auth.user_id]
    cid = request.args.get("client_id")
    if cid is not None:
        items = [r for r in items if r["client_id"] == cid]
    jid = request.args.get("jurisdiction_id")
    if jid is not None:
        items = [r for r in items if r["jurisdiction_id"] == jid]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    period = request.args.get("period")
    if period is not None:
        items = [r for r in items if r["period"] == period]
    supersedes = request.args.get("supersedes_return_id")
    if supersedes is not None:
        items = [r for r in items if r.get("supersedes_return_id") == supersedes]
    page, limit, offset, total = paginate(items)
    return success_list([ret_view(r) for r in page], limit, offset, total)


@bp.route("/returns/<returnId>", methods=["GET"])
def get_return(returnId):
    auth = authenticate()
    require_roles(auth, READ_ROLES)
    r = _get_return(returnId)
    check_client_identity(auth, r["client_id"])
    return success_object(ret_view(r))


@bp.route("/returns/<returnId>/file", methods=["POST"])
def file_return(returnId):
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    r = _get_return(returnId)
    if r["status"] != "DRAFT":
        raise errors.invalid_state("Return must be DRAFT to file")
    # Registration gate for electronic filing
    if r["filing_method"] == "ELECTRONIC":
        reg = registration_for(r["client_id"], r["jurisdiction_id"])
        if not reg or reg["status"] != "VERIFIED":
            raise errors.registration_not_verified("Registration is not VERIFIED")
    # Temporal gate: period must be closed. The period closes once the logical
    # clock reaches the start of the day after the period's final day (filing
    # on the last day of the period itself is too early).
    _, end = period_bounds(r["period"])
    from datetime import timedelta
    close_at = (end + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    if now_dt() < close_at:
        raise errors.period_not_closed("Return period is not closed")
    r["status"] = "FILED"
    r["filed_at"] = now_iso()
    r["_filed_by"] = auth.user_id
    r["expected_liability_cents"] = bureau_books_liability(r["client_id"], r["period"])
    if "-Q" in r["period"]:
        jur = store.jurisdictions.get(r["jurisdiction_id"])
        r["shortfall_penalty_exposure_cents"] = shortfall_penalty(r, jur)
    touch(r)
    return success_object(ret_view(r))


def _sod_check(auth, ret):
    if ret.get("_filed_by") is not None and ret["_filed_by"] == auth.user_id:
        raise errors.sod_violation("The filer cannot perform this action")


@bp.route("/returns/<returnId>/accept", methods=["POST"])
def accept_return(returnId):
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    r = _get_return(returnId)
    if r["status"] != "FILED":
        raise errors.invalid_state("Return must be FILED to accept")
    _sod_check(auth, r)
    r["status"] = "ACCEPTED"
    touch(r)
    return success_object(ret_view(r))


@bp.route("/returns/<returnId>/reject", methods=["POST"])
def reject_return(returnId):
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    r = _get_return(returnId)
    if r["status"] != "FILED":
        raise errors.invalid_state("Return must be FILED to reject")
    _sod_check(auth, r)
    r["status"] = "REJECTED"
    touch(r)
    return success_object(ret_view(r))


@bp.route("/returns/<returnId>/redraft", methods=["POST"])
def redraft_return(returnId):
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    r = _get_return(returnId)
    if r["status"] != "REJECTED":
        raise errors.invalid_state("Return must be REJECTED to redraft")
    r["status"] = "DRAFT"
    r["filed_at"] = None
    touch(r)
    return success_object(ret_view(r))


@bp.route("/returns/<returnId>/reconcile", methods=["POST"])
def reconcile_return(returnId):
    auth = authenticate()
    require_roles(auth, {"BureauTaxFiler"})
    r = _get_return(returnId)
    if r["status"] != "ACCEPTED":
        raise errors.invalid_state("Return must be ACCEPTED to reconcile")
    _sod_check(auth, r)
    for n in store.notices.values():
        if n["return_id"] == returnId and n["status"] in ("OPEN", "IN_REVIEW"):
            raise errors.open_notice_blocks("Open notice blocks reconciliation")
    r["status"] = "RECONCILED"
    r["reconciled_at"] = now_iso()
    r["expected_liability_cents"] = agency_confirmed_liability(
        r["client_id"], r["jurisdiction_id"], r["period"])
    touch(r)
    return success_object(ret_view(r))


@bp.route("/returns/<returnId>/amendments", methods=["GET"])
def list_return_amendments(returnId):
    auth = authenticate()
    require_roles(auth, READ_ROLES)
    r = _get_return(returnId)
    check_client_identity(auth, r["client_id"])
    items = [a for a in store.amendments.values() if a["return_id"] == returnId]
    page, limit, offset, total = paginate(items)
    return success_list([public(a) for a in page], limit, offset, total)


@bp.route("/returns/<returnId>/notices", methods=["GET"])
def list_return_notices(returnId):
    auth = authenticate()
    require_roles(auth, READ_ROLES)
    r = _get_return(returnId)
    check_client_identity(auth, r["client_id"])
    items = [n for n in store.notices.values() if n["return_id"] == returnId]
    status = request.args.get("status")
    if status is not None:
        items = [n for n in items if n["status"] == status]
    page, limit, offset, total = paginate(items)
    return success_list([public(n) for n in page], limit, offset, total)
