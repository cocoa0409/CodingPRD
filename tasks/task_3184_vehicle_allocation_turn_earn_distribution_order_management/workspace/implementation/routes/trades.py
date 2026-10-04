"""Dealer-to-dealer trades (PRD §3.9)."""
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from flask import Blueprint, request

import errors as err
from db import get_store, now_iso
from middleware import auth_context, require_dealer_owns
from response import success_list, success_object
from services.core import (PENALTY_PER_UNIT, TRADE_TTL_DAYS, get_da, get_dml,
                           is_new_point, recompute_da_pools)
from util import (bump, fmt_dt, new_entity, now_dt, opt_int, parse_dt,
                  req_int, req_str, sweep_all_trades, sweep_trade)

bp = Blueprint("trades", __name__)

READ = ["RegionalAllocator", "Dealer"]


def _body() -> dict:
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _get_trade_or_404(trade_id):
    trade = get_store("dealer_trades").get(trade_id)
    if trade is None:
        raise err.not_found("trade not found")
    sweep_trade(trade)
    return trade


@bp.post("/wholesale/dealer-trades")
def create_trade():
    _role, user_id = auth_context(["Dealer"])
    body = _body()
    from_dealer_id = req_str(body, "from_dealer_id")
    to_dealer_id = req_str(body, "to_dealer_id")
    run_id = req_str(body, "run_id")
    units = req_int(body, "units")

    # Priority 3: the proposer must be the acting dealer.
    require_dealer_owns(user_id, from_dealer_id)

    # Priority 4: FK existence in declared field order.
    dealers = get_store("dealers")
    from_dealer = dealers.get(from_dealer_id)
    if from_dealer is None:
        raise err.not_found("from dealer not found")
    to_dealer = dealers.get(to_dealer_id)
    if to_dealer is None:
        raise err.not_found("to dealer not found")
    if run_id not in get_store("allocation_runs"):
        raise err.not_found("run not found")

    # Priority 13: trade referential integrity.
    if from_dealer_id == to_dealer_id:
        raise err.trade_invalid("self-trade")
    if units < 1:
        raise err.trade_invalid("units must be >= 1")
    if from_dealer["region_id"] != to_dealer["region_id"]:
        raise err.trade_invalid("cross-region trade")

    expires = fmt_dt(now_dt() + timedelta(days=TRADE_TTL_DAYS))
    trade = new_entity({
        "from_dealer_id": from_dealer_id,
        "to_dealer_id": to_dealer_id,
        "run_id": run_id,
        "units": units,
        "state": "PROPOSED",
        "counter_units": None,
        "expires_at": expires,
        "executed_at": None,
    })
    get_store("dealer_trades")[trade["id"]] = trade
    return success_object(trade, 201)


@bp.get("/wholesale/dealer-trades")
def list_trades():
    auth_context(READ)
    sweep_all_trades()
    rows = list(get_store("dealer_trades").values())
    for key in ("from_dealer_id", "to_dealer_id", "run_id", "state"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r.get(key) == value]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return success_list(rows)


@bp.get("/wholesale/dealer-trades/<tid>")
def get_trade(tid):
    auth_context(READ)
    return success_object(_get_trade_or_404(tid))


@bp.post("/wholesale/dealer-trades/<tid>/counter")
def counter_trade(tid):
    _role, user_id = auth_context(["Dealer"])
    trade = _get_trade_or_404(tid)
    if trade["state"] == "PROPOSED":
        require_dealer_owns(user_id, trade["to_dealer_id"])
    elif trade["state"] == "COUNTERED":
        require_dealer_owns(user_id, trade["from_dealer_id"])
    else:
        raise err.invalid_state("trade is not PROPOSED or COUNTERED")
    counter_units = req_int(_body(), "counter_units", 1)
    if now_dt() >= parse_dt(trade["expires_at"]):
        raise err.trade_expired()
    if trade["state"] == "PROPOSED":
        trade["state"] = "COUNTERED"
        trade["counter_units"] = counter_units
    else:
        # Re-counter: back to PROPOSED, units updated (§3.9).
        trade["state"] = "PROPOSED"
        trade["units"] = counter_units
    bump(trade)
    return success_object(trade)


@bp.post("/wholesale/dealer-trades/<tid>/accept")
def accept_trade(tid):
    _role, user_id = auth_context(["Dealer"])
    trade = _get_trade_or_404(tid)
    if trade["state"] != "PROPOSED":
        raise err.invalid_state("trade is not PROPOSED")
    require_dealer_owns(user_id, trade["to_dealer_id"])
    if now_dt() >= parse_dt(trade["expires_at"]):
        raise err.trade_expired()
    trade["state"] = "ACCEPTED"
    bump(trade)
    return success_object(trade)


@bp.post("/wholesale/dealer-trades/<tid>/decline")
def decline_trade(tid):
    _role, user_id = auth_context(["Dealer"])
    trade = _get_trade_or_404(tid)
    if trade["state"] not in ("PROPOSED", "COUNTERED"):
        raise err.invalid_state("trade is not PROPOSED or COUNTERED")
    if user_id not in (trade["to_dealer_id"], trade["from_dealer_id"]):
        raise err.forbidden()
    trade["state"] = "DECLINED"
    bump(trade)
    return success_object(trade)


@bp.post("/wholesale/dealer-trades/<tid>/cancel")
def cancel_trade(tid):
    _role, user_id = auth_context(["Dealer"])
    trade = _get_trade_or_404(tid)
    if trade["state"] not in ("PROPOSED", "COUNTERED"):
        raise err.invalid_state("trade is not PROPOSED or COUNTERED")
    require_dealer_owns(user_id, trade["from_dealer_id"])
    trade["state"] = "CANCELLED"
    bump(trade)
    return success_object(trade)


@bp.post("/wholesale/dealer-trades/<tid>/execute")
def execute_trade(tid):
    auth_context(["RegionalAllocator"])
    trade = _get_trade_or_404(tid)
    run = get_store("allocation_runs").get(trade["run_id"])
    if run is None:
        raise err.not_found("run not found")
    if trade["state"] != "ACCEPTED":
        raise err.invalid_state("trade is not ACCEPTED")
    if run["status"] != "PUBLISHED":
        raise err.parent_not_active("run is not PUBLISHED")
    body = _body()
    expected_run_version = req_int(body, "expected_run_version", 1)
    if expected_run_version != run["version"]:
        raise err.stale_run_version()
    units = trade["units"]
    da_from = get_da(trade["run_id"], trade["from_dealer_id"])
    da_to = get_da(trade["run_id"], trade["to_dealer_id"])
    if da_from is None or da_to is None:
        raise err.not_found("dealer allocation not found")
    if (da_from["final_units"] - da_from["consumed_units"]) < units:
        raise err.trade_exceeds_pool()

    from_dealer = get_store("dealers")[trade["from_dealer_id"]]
    da_from["adjustment_units"] -= units
    da_to["adjustment_units"] += units
    recompute_da_pools(da_from, run, from_dealer)
    recompute_da_pools(da_to, run, get_store("dealers")[trade["to_dealer_id"]])
    bump(da_from)
    bump(da_to)

    # Trade-earn penalty (§3.9): waived for new points.
    if not is_new_point(from_dealer, now_dt()):
        dml = get_dml(trade["from_dealer_id"], run["model_line_id"], create=True)
        penalty = float(Decimal(str(units * PENALTY_PER_UNIT)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP))
        new_credit = max(0.0, float(Decimal(str(dml["earned_credit_units"] - penalty)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP)))
        if new_credit != dml["earned_credit_units"]:
            dml["earned_credit_units"] = new_credit
            bump(dml)

    trade["state"] = "EXECUTED"
    trade["executed_at"] = now_iso()
    bump(trade)
    bump(run)
    return success_object(trade)
