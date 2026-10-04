"""ExhibitorAgreement endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import (
    ERR_AGREEMENT_NOT_FOUND, ERR_MARKET_NOT_FOUND, ERR_INVALID_STATE,
    ERR_MARKET_NOT_APPROVED, ERR_NO_OPERATING_AUDITORIUM, ERR_INVALID_REQUEST,
    bad_request, conflict, not_found,
)
from util import (
    require_role, require_auth, get_body, req_str, req_int, req_enum, req_number,
    parse_pagination, paginate, success_object, success_list, stamp_new, touch,
    sort_by_created, parse_iso_datetime, iso_format, forbidden,
)
from domain import (
    serialize_agreement, serialize_auditorium, serialize_revenue_share_statement,
    terminate_agreement,
)

bp = Blueprint("agreements", __name__)


def get_agreement_or_404(agreement_id):
    a = db.agreements.get(agreement_id)
    if a is None:
        raise not_found(ERR_AGREEMENT_NOT_FOUND, f"Agreement {agreement_id} not found")
    return a


def _check_exhibitor_ownership(agreement):
    """ExhibitorFinanceUser may only access own agreement."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role == "ExhibitorFinanceUser" and agreement.get("id") != user_id:
        raise forbidden("ExhibitorFinanceUser may only access own agreement")


@bp.post("/v1/agreements")
def create_agreement():
    require_role("PlatformContractManager")
    body = get_body()
    exhibitor_legal_name = req_str(body, "exhibitor_legal_name")
    market_id = req_str(body, "market_id")
    agreement_type = req_enum(body, "agreement_type", {"REVENUE_SHARE", "LEASE"})
    committed_screen_count = req_int(body, "committed_screen_count")
    # Body FK existence check (declared input order: market_id comes 2nd)
    market = db.markets.get(market_id)
    if market is None:
        raise not_found(ERR_MARKET_NOT_FOUND, f"Market {market_id} not found")

    t1 = t2 = t3 = None
    lease_fee = None
    if agreement_type == "REVENUE_SHARE":
        t1 = req_number(body, "revenue_share_tier1_pct")
        t2 = req_number(body, "revenue_share_tier2_pct")
        t3 = req_number(body, "revenue_share_tier3_pct")
    else:
        v = body.get("annual_lease_fee_cents")
        if isinstance(v, bool) or not isinstance(v, int):
            raise bad_request(ERR_INVALID_REQUEST,
                              "annual_lease_fee_cents is required and must be an integer for LEASE")
        lease_fee = v

    term_start_raw = body.get("term_start_date")
    term_end_raw = body.get("term_end_date")
    term_start = parse_iso_datetime(term_start_raw, "term_start_date")
    term_end = parse_iso_datetime(term_end_raw, "term_end_date")

    agr = {
        "exhibitor_legal_name": exhibitor_legal_name,
        "market_id": market_id,
        "agreement_type": agreement_type,
        "committed_screen_count": committed_screen_count,
        "revenue_share_tier1_pct": t1,
        "revenue_share_tier2_pct": t2,
        "revenue_share_tier3_pct": t3,
        "annual_lease_fee_cents": lease_fee,
        "term_start_date": iso_format(term_start),
        "term_end_date": iso_format(term_end),
        "_term_start_date_dt": term_start,
        "_term_end_date_dt": term_end,
        "total_slots_committed_count": 0,
        "status": "NEGOTIATING",
    }
    stamp_new(agr)
    db.agreements[agr["id"]] = agr
    return success_object(serialize_agreement(agr), 201)


@bp.get("/v1/agreements")
def list_agreements():
    user_id, role = require_auth()
    if role not in ("NetworkPlanner", "PlatformContractManager", "BoxOfficeAnalyst", "ExhibitorFinanceUser"):
        raise forbidden(f"Role {role} is not permitted to perform this operation")
    limit, offset = parse_pagination()
    items = sort_by_created(list(db.agreements.values()))
    market_id = request.args.get("market_id")
    status = request.args.get("status")
    if market_id:
        items = [a for a in items if a.get("market_id") == market_id]
    if status:
        items = [a for a in items if a.get("status") == status]
    if role == "ExhibitorFinanceUser":
        items = [a for a in items if a.get("id") == user_id]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_agreement(a) for a in page], total, limit, offset)


@bp.get("/v1/agreements/<agreement_id>")
def get_agreement(agreement_id):
    user_id, role = require_auth()
    if role not in ("NetworkPlanner", "PlatformContractManager", "BoxOfficeAnalyst", "ExhibitorFinanceUser"):
        raise forbidden(f"Role {role} is not permitted to perform this operation")
    agr = get_agreement_or_404(agreement_id)
    _check_exhibitor_ownership(agr)
    return success_object(serialize_agreement(agr))


@bp.post("/v1/agreements/<agreement_id>/sign")
def sign_agreement(agreement_id):
    require_role("PlatformContractManager")
    agr = get_agreement_or_404(agreement_id)
    if agr.get("status") != "NEGOTIATING":
        raise conflict(ERR_INVALID_STATE, f"Agreement in state {agr.get('status')} cannot be signed")
    market = db.markets.get(agr.get("market_id"))
    if market is None or market.get("status") not in ("APPROVED", "BUILDING", "LIVE"):
        raise conflict(ERR_MARKET_NOT_APPROVED,
                       "Market must be APPROVED, BUILDING or LIVE to sign")
    agr["status"] = "SIGNED"
    touch(agr)
    return success_object(serialize_agreement(agr))


@bp.post("/v1/agreements/<agreement_id>/activate")
def activate_agreement(agreement_id):
    require_role("PlatformContractManager")
    agr = get_agreement_or_404(agreement_id)
    if agr.get("status") != "SIGNED":
        raise conflict(ERR_INVALID_STATE, f"Agreement in state {agr.get('status')} cannot be activated")
    for aud in db.auditoriums.values():
        if aud.get("agreement_id") == agr["id"] and aud.get("status") == "OPERATING":
            agr["status"] = "ACTIVE"
            touch(agr)
            return success_object(serialize_agreement(agr))
    raise conflict(ERR_NO_OPERATING_AUDITORIUM,
                   "At least one OPERATING auditorium required to activate")


@bp.post("/v1/agreements/<agreement_id>/terminate")
def terminate_agreement_ep(agreement_id):
    require_role("PlatformContractManager")
    agr = get_agreement_or_404(agreement_id)
    if agr.get("status") in ("TERMINATED", "EXPIRED"):
        raise conflict(ERR_INVALID_STATE, f"Agreement in state {agr.get('status')} cannot be terminated")
    prior = agr["status"]
    agr["status"] = "TERMINATED"
    touch(agr)
    terminate_agreement(agr, prior)
    return success_object(serialize_agreement(agr))


@bp.get("/v1/agreements/<agreement_id>/auditoriums")
def list_agreement_auditoriums(agreement_id):
    require_role("NetworkPlanner", "PlatformContractManager", "FieldEngineer", "ReleaseScheduler")
    agr = get_agreement_or_404(agreement_id)
    limit, offset = parse_pagination()
    items = [a for a in db.auditoriums.values() if a.get("agreement_id") == agr["id"]]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_auditorium(a) for a in page], total, limit, offset)


@bp.get("/v1/agreements/<agreement_id>/revenue-share-statements")
def list_agreement_statements(agreement_id):
    user_id, role = require_auth()
    if role not in ("PlatformContractManager", "BoxOfficeAnalyst", "ExhibitorFinanceUser"):
        raise forbidden(f"Role {role} is not permitted to perform this operation")
    agr = get_agreement_or_404(agreement_id)
    _check_exhibitor_ownership(agr)
    limit, offset = parse_pagination()
    items = [s for s in db.revenue_share_statements.values() if s.get("agreement_id") == agr["id"]]
    items = sort_by_created(items)
    page, total = paginate(items, limit, offset)
    return success_list([serialize_revenue_share_statement(s) for s in page], total, limit, offset)
