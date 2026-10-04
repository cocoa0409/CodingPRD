"""RevenueShareStatement endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import (
    ERR_STATEMENT_NOT_FOUND, ERR_AGREEMENT_NOT_FOUND, ERR_WINDOW_NOT_FOUND,
    ERR_SLOT_NOT_FOUND, ERR_INVALID_STATE, ERR_INVALID_REQUEST, ERR_UNRESOLVED_REPORTS,
    bad_request, conflict, not_found, forbidden,
)
from util import (
    require_role, require_auth, get_body, req_str, req_int,
    parse_pagination, paginate, success_object, success_list, stamp_new, touch,
    sort_by_created,
)
from domain import serialize_revenue_share_statement, recompute_statement

bp = Blueprint("revenue_share_statements", __name__)


def get_statement_or_404(statement_id):
    s = db.revenue_share_statements.get(statement_id)
    if s is None:
        raise not_found(ERR_STATEMENT_NOT_FOUND, f"Statement {statement_id} not found")
    return s


def _owns_statement(user_id, stmt):
    return stmt.get("agreement_id") == user_id


@bp.post("/v1/revenue-share-statements")
def create_statement():
    require_role("BoxOfficeAnalyst")
    body = get_body()
    agreement_id = req_str(body, "agreement_id")
    window_id = req_str(body, "window_id")
    if agreement_id not in db.agreements:
        raise not_found(ERR_AGREEMENT_NOT_FOUND, f"Agreement {agreement_id} not found")
    if window_id not in db.release_windows:
        raise not_found(ERR_WINDOW_NOT_FOUND, f"Window {window_id} not found")
    stmt = {
        "agreement_id": agreement_id,
        "window_id": window_id,
        "statement_lines": [],
        "provisional_total_cents": 0,
        "final_total_cents": 0,
        "status": "DRAFT",
    }
    stamp_new(stmt)
    db.revenue_share_statements[stmt["id"]] = stmt
    return success_object(serialize_revenue_share_statement(stmt), 201)


@bp.get("/v1/revenue-share-statements")
def list_statements():
    user_id, role = require_auth()
    if role not in ("BoxOfficeAnalyst", "PlatformContractManager", "ExhibitorFinanceUser"):
        raise forbidden(f"Role {role} is not permitted to perform this operation")
    limit, offset = parse_pagination()
    items = sort_by_created(list(db.revenue_share_statements.values()))
    agreement_id = request.args.get("agreement_id")
    window_id = request.args.get("window_id")
    status = request.args.get("status")
    if agreement_id:
        items = [s for s in items if s.get("agreement_id") == agreement_id]
    if window_id:
        items = [s for s in items if s.get("window_id") == window_id]
    if status:
        items = [s for s in items if s.get("status") == status]
    if role == "ExhibitorFinanceUser":
        items = [s for s in items if _owns_statement(user_id, s)]
    page, total = paginate(items, limit, offset)
    return success_list([serialize_revenue_share_statement(s) for s in page], total, limit, offset)


@bp.get("/v1/revenue-share-statements/<statement_id>")
def get_statement(statement_id):
    user_id, role = require_auth()
    if role not in ("BoxOfficeAnalyst", "PlatformContractManager", "ExhibitorFinanceUser"):
        raise forbidden(f"Role {role} is not permitted to perform this operation")
    stmt = get_statement_or_404(statement_id)
    if role == "ExhibitorFinanceUser" and not _owns_statement(user_id, stmt):
        raise forbidden("ExhibitorFinanceUser may only access own agreement's statements")
    return success_object(serialize_revenue_share_statement(stmt))


@bp.post("/v1/revenue-share-statements/<statement_id>/issue")
def issue_statement(statement_id):
    require_role("BoxOfficeAnalyst")
    stmt = get_statement_or_404(statement_id)
    if stmt.get("status") != "DRAFT":
        raise conflict(ERR_INVALID_STATE, f"Statement in state {stmt.get('status')} cannot be issued")
    # every slot in window with status CONFIRMED/HELD_OVER/PULLED: no RECEIVED reports
    for slot in db.screen_slots.values():
        if slot.get("window_id") != stmt.get("window_id"):
            continue
        if slot.get("status") not in ("CONFIRMED", "HELD_OVER", "PULLED"):
            continue
        for rpt in db.box_office_reports.values():
            if rpt.get("screen_slot_id") == slot["id"] and rpt.get("status") == "RECEIVED":
                raise conflict(ERR_UNRESOLVED_REPORTS,
                               "Some box office reports are still RECEIVED")
    recompute_statement(stmt)
    stmt["status"] = "ISSUED"
    touch(stmt)
    return success_object(serialize_revenue_share_statement(stmt))


@bp.post("/v1/revenue-share-statements/<statement_id>/reconcile")
def reconcile_statement(statement_id):
    require_role("PlatformContractManager")
    stmt = get_statement_or_404(statement_id)
    if stmt.get("status") != "ISSUED":
        raise conflict(ERR_INVALID_STATE, f"Statement in state {stmt.get('status')} cannot be reconciled")
    stmt["status"] = "RECONCILED"
    touch(stmt)
    return success_object(serialize_revenue_share_statement(stmt))


@bp.post("/v1/revenue-share-statements/<statement_id>/dispute")
def dispute_statement(statement_id):
    user_id, role = require_auth()
    if role != "ExhibitorFinanceUser":
        raise forbidden(f"Role {role} is not permitted to perform this operation")
    stmt = get_statement_or_404(statement_id)
    if not _owns_statement(user_id, stmt):
        raise forbidden("ExhibitorFinanceUser may only dispute own agreement's statements")
    if stmt.get("status") != "ISSUED":
        raise conflict(ERR_INVALID_STATE, f"Statement in state {stmt.get('status')} cannot be disputed")
    stmt["status"] = "DISPUTED"
    touch(stmt)
    return success_object(serialize_revenue_share_statement(stmt))


@bp.post("/v1/revenue-share-statements/<statement_id>/apply-adjustment")
def apply_adjustment(statement_id):
    require_role("BoxOfficeAnalyst")
    stmt = get_statement_or_404(statement_id)
    if stmt.get("status") != "DISPUTED":
        raise conflict(ERR_INVALID_STATE, f"Statement in state {stmt.get('status')} cannot be adjusted")
    body = get_body()
    screen_slot_id = req_str(body, "screen_slot_id")
    adjustment_cents = req_int(body, "adjustment_cents")
    adjustment_reason = req_str(body, "adjustment_reason")
    slot = db.screen_slots.get(screen_slot_id)
    if slot is None:
        raise not_found(ERR_SLOT_NOT_FOUND, f"Slot {screen_slot_id} not found")

    recompute_statement(stmt)
    line = None
    for l in stmt["statement_lines"]:
        if l.get("screen_slot_id") == screen_slot_id:
            line = l
            break
    if line is None:
        raise bad_request(ERR_INVALID_REQUEST,
                          "screen_slot_id does not correspond to a statement line")
    adjustment = {
        "screen_slot_id": screen_slot_id,
        "adjustment_cents": adjustment_cents,
        "adjustment_reason": adjustment_reason,
    }
    line["adjustments"] = list(line.get("adjustments", [])) + [adjustment]
    # Apply: agreed_share_cents += adjustment, exhibitor_retained_cents -= adjustment
    line["agreed_share_cents"] = line.get("agreed_share_cents", 0) + adjustment_cents
    line["exhibitor_retained_cents"] = line.get("gross_reported_cents", 0) - line["agreed_share_cents"]
    # Recompute final total: sum of line agreed_share_cents
    stmt["final_total_cents"] = sum(l.get("agreed_share_cents", 0) for l in stmt["statement_lines"])
    stmt["status"] = "ADJUSTED"
    touch(stmt)
    return success_object(serialize_revenue_share_statement(stmt))


@bp.post("/v1/revenue-share-statements/<statement_id>/reissue")
def reissue_statement(statement_id):
    require_role("BoxOfficeAnalyst")
    stmt = get_statement_or_404(statement_id)
    if stmt.get("status") != "ADJUSTED":
        raise conflict(ERR_INVALID_STATE, f"Statement in state {stmt.get('status')} cannot be reissued")
    stmt["status"] = "ISSUED"
    touch(stmt)
    return success_object(serialize_revenue_share_statement(stmt))
