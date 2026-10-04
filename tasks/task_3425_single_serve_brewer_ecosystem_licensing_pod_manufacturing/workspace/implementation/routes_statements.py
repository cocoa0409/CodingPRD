"""Royalty statements: create (provisional), issue/dispute/settle (final)."""
from datetime import date, datetime
from flask import Blueprint, request

from store import db
from helpers import (
    ApiError, body, created, find, init_common, list_ok, need, ok,
    parse_period_val, period_not_future, require_roles, touch, v_enum, v_int,
)
from calc import bracket_cents, compute_final_royalty
from routes_licensing import agreement_write_gate
from serializers import statement_out

bp = Blueprint("statements", __name__)

STATEMENT_TARGETS = ("ISSUED", "DISPUTED", "SETTLED")

_DECLARED = {
    ("DRAFT", "ISSUED"), ("ISSUED", "DISPUTED"), ("DISPUTED", "ISSUED"),
    ("ISSUED", "SETTLED"),
}


def _agreement_state_gate(agr):
    """Shared gate for statement creation and issue: expiry first (handled by
    agreement_write_gate), then SUSPENDED -> ERR_LICENSE_SUSPENDED, then any
    other non-ACTIVE -> ERR_INVALID_STATE."""
    agreement_write_gate(agr)
    if agr["status"] == "SUSPENDED":
        raise ApiError("ERR_LICENSE_SUSPENDED", 409,
                       "Statement work is refused while the agreement is SUSPENDED")
    if agr["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Statement operations require an ACTIVE agreement")


def _period_within_window(agr, period):
    start = datetime.strptime(agr["effective_start"], "%Y-%m-%d").date()
    end = datetime.strptime(agr["effective_end"], "%Y-%m-%d").date()
    first = date(int(period[:4]), int(period[5:7]), 1)
    if not (start <= first <= end):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "Statement period must fall within the agreement window")


@bp.post("/license-agreements/<rid>/royalty-statements")
@require_roles("FinanceAnalyst")
def create_statement(rid):
    agr = find("agreements", rid)
    b = body()
    period = parse_period_val(need(b, "period"))
    period_not_future(period)
    _period_within_window(agr, period)
    sell_in = v_int(b, "sell_in_units")
    sell_through = v_int(b, "sell_through_units")
    share = v_int(b, "unlicensed_share_pct", minv=0, maxv=100)
    agreement_write_gate(agr)
    for s in db["statements"].values():
        if s["agreement_id"] == agr["id"] and s["period"] == period:
            raise ApiError("ERR_DUPLICATE_STATEMENT_PERIOD", 409,
                           "A statement already exists for this agreement and period")
    if agr["status"] == "SUSPENDED":
        raise ApiError("ERR_LICENSE_SUSPENDED", 409,
                       "Statement work is refused while the agreement is SUSPENDED")
    if agr["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Statement creation requires an ACTIVE agreement")
    stmt = init_common({
        "agreement_id": agr["id"],
        "period": period,
        "sell_in_units": sell_in,
        "sell_through_units": sell_through,
        "unlicensed_share_pct": share,
        "provisional_royalty_cents": bracket_cents(sell_in, 0, agr["royalty_tiers"]),
        "final_royalty_cents": None,
        "dispute_count": 0,
        "status": "DRAFT",
    })
    db["statements"][stmt["id"]] = stmt
    return created(statement_out(stmt))


@bp.get("/license-agreements/<rid>/royalty-statements")
@require_roles("FinanceAnalyst", "LicensingManager")
def list_statements(rid):
    agr = find("agreements", rid)
    items = [s for s in db["statements"].values() if s["agreement_id"] == agr["id"]]
    f_period = request.args.get("period")
    f_status = request.args.get("status")
    if f_period is not None:
        items = [s for s in items if s["period"] == f_period]
    if f_status is not None:
        items = [s for s in items if s["status"] == f_status]
    items.sort(key=lambda s: (s["created_at"], s["_seq"]))
    return list_ok(items, statement_out)


@bp.post("/royalty-statements/<rid>/transition")
@require_roles("FinanceAnalyst")
def transition_statement(rid):
    stmt = find("statements", rid)
    b = body()
    target = v_enum(b, "target_state", STATEMENT_TARGETS)
    new_sell_through = v_int(b, "sell_through_units", required=False)
    new_share = v_int(b, "unlicensed_share_pct", required=False, minv=0, maxv=100)
    if target == "DISPUTED" and not isinstance(b.get("dispute_reason"), str):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "dispute_reason is required when disputing")
    if (stmt["status"], target) not in _DECLARED:
        raise ApiError("ERR_INVALID_STATE", 409,
                       "No declared transition from %s to %s" % (stmt["status"], target))
    if target == "ISSUED":
        agr = db["agreements"][stmt["agreement_id"]]
        _agreement_state_gate(agr)
        if new_sell_through is not None:
            stmt["sell_through_units"] = new_sell_through
        if new_share is not None:
            stmt["unlicensed_share_pct"] = new_share
        stmt["final_royalty_cents"] = compute_final_royalty(stmt, agr)
    elif target == "DISPUTED":
        stmt["dispute_count"] += 1
    stmt["status"] = target
    touch(stmt)
    return ok(statement_out(stmt))
