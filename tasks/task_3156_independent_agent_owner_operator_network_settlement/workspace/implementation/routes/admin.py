"""Administrative test-driving capabilities: the logical clock and event drivers."""
from __future__ import annotations

from flask import Blueprint

from cascades import post_ledger, refresh_balances
from common import (
    STATE, bad_request, body, client_fields, clock_dt, clock_str, fetch, ok,
    parse_ts, require_int, require_role, require_text,
)
from domain import (
    band_rate, effective_per_load_fee, reevaluate_all_derived, sync_bco,
)

bp = Blueprint("admin", __name__)


def _month_bounds(period_month: str):
    if not isinstance(period_month, str) or len(period_month) != 7 \
            or period_month[4] != "-":
        raise bad_request("period_month must be formatted as YYYY-MM.")
    year, month = int(period_month[:4]), int(period_month[5:])
    if month < 1 or month > 12:
        raise bad_request("period_month must carry a month between 01 and 12.")
    start = parse_ts(f"{year:04d}-{month:02d}-01T00:00:00Z", "period_month")
    end = parse_ts(
        f"{year + (1 if month == 12 else 0):04d}-{1 if month == 12 else month + 1:02d}"
        f"-01T00:00:00Z", "period_month")
    return start, end


def _row(agent_id, start, end):
    eligible = []
    for load in STATE.loads.values():
        if load["agent_id"] != agent_id:
            continue
        if load["status"] not in ("AWARDED", "COVERED", "IN_TRANSIT", "DELIVERED",
                                  "SETTLED"):
            continue
        created = parse_ts(load["created_at"], "created_at")
        if start <= created < end:
            eligible.append(load)
    count = len(eligible)
    paid = sum(1 for load in STATE.loads.values()
               if load["agent_id"] == agent_id
               and load["status"] in ("DELIVERED", "SETTLED"))
    return eligible, count, paid


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_role("NetworkAdministrator")
    fields = client_fields(body(), ["current_utc"])
    value = require_text(fields, "current_utc")
    parse_ts(value, "current_utc")
    STATE.clock = value
    reevaluate_all_derived()
    return ok({})


@bp.post("/_events/run_advance_post")
def run_advance_post():
    require_role("SettlementOperator", "NetworkAdministrator")
    fields = client_fields(body(), [
        "capacity_owner_id", "amount_cents", "effective_at",
    ])
    bco = fetch("capacity_owner", require_text(fields, "capacity_owner_id"))
    amount = require_int(fields, "amount_cents", minimum=1)
    effective = require_text(fields, "effective_at")
    parse_ts(effective, "effective_at")
    from domain import escrow_balance_of, outstanding_advance_of
    if escrow_balance_of(bco["id"]) - amount < 0:
        from common import ApiError
        raise ApiError("ERR_ESCROW_BALANCE_INSUFFICIENT", 402,
                       "The advance would drive the escrow balance below zero.")
    row = post_ledger(bco["id"], "ADVANCE", amount, effective)
    refresh_balances(bco["id"])
    sync_bco(bco)
    return ok({
        "advance_transaction_id": row["id"],
        "escrow_balance_cents": escrow_balance_of(bco["id"]),
        "outstanding_advance_cents": outstanding_advance_of(bco["id"]),
    })


@bp.post("/_events/run_period_close")
def run_period_close():
    require_role("NetworkAdministrator")
    fields = client_fields(body(), ["agent_id", "period_month"])
    agent = fetch("agent", require_text(fields, "agent_id"))
    period_month = require_text(fields, "period_month")
    start, end = _month_bounds(period_month)
    _eligible, count, paid = _row(agent["id"], start, end)
    from domain import band_rate
    rate = band_rate(count)
    return ok({
        "period_month": period_month,
        "eligible_load_count": count,
        "paid_load_count": paid,
        "per_load_fee_cents": rate,
        "period_fee_cents": count * rate,
        "effective_per_load_fee_cents": effective_per_load_fee(count),
    })