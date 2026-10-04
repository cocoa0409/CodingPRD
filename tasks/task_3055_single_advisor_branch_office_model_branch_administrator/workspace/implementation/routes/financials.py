"""Financial period and charge routes (§2.8, §3.5, §3.6)."""
from flask import Blueprint, request

import db
from errors import err
from middleware import auth_context, require_role
from helpers import (
    body_json, require_fields, require_enum, parse_dt, get_or_404, stamp_new,
    touch, paginate, sort_by_created_at, recompute_period, recompute_tier,
)
from response import success_object, success_list

bp = Blueprint("financials", __name__)
PERIODS = "/branch-office/financial-periods"
CHARGES = "/branch-office/charges"

CHARGE_TYPES = {"LEASE_RENT", "BOA_PAYROLL", "EQUIPMENT", "DEFICIT_CARRYOVER"}


def _periods_for_branch(branch_id):
    return [p for p in db.financial_periods.values() if p.get("branch_id") == branch_id]


def _check_period_overlap(branch_id, start, end, exclude_id=None):
    """Half-open [start, end) overlap with any existing period of the branch."""
    for p in _periods_for_branch(branch_id):
        if exclude_id and p["id"] == exclude_id:
            continue
        ps = parse_dt(p["period_start"], "period_start")
        pe = parse_dt(p["period_end"], "period_end")
        if start < pe and ps < end:
            raise err("ERR_INVALID_REQUEST", "Financial periods for a branch must not overlap.")


@bp.route(PERIODS, methods=["POST"])
def create_period():
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    body = body_json()
    require_fields(body, ["branch_id", "period_start", "period_end"])
    branch = get_or_404(db.branches, body["branch_id"], "Branch")
    start = parse_dt(body["period_start"], "period_start")
    end = parse_dt(body["period_end"], "period_end")
    if end <= start:
        raise err("ERR_INVALID_REQUEST", "period_end must be after period_start.")
    _check_period_overlap(branch["id"], start, end)
    period = stamp_new({
        "branch_id": branch["id"],
        "period_start": db.iso_format(start),
        "period_end": db.iso_format(end),
        "status": "OPEN",
        "gross_revenue_cents": 0,
        "total_charges_cents": 0,
        "net_profit_cents": 0,
        "advisor_share_cents": 0,
        "deficit_carryforward_cents": 0,
    })
    db.financial_periods[period["id"]] = period
    return success_object(period, 201)


@bp.route(f"{PERIODS}/<pid>", methods=["GET"])
def get_period(pid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin", "Advisor"})
    return success_object(get_or_404(db.financial_periods, pid, "BranchFinancialPeriod"))


@bp.route(f"{PERIODS}/<pid>/charges", methods=["POST"])
def post_charge(pid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    period = get_or_404(db.financial_periods, pid, "BranchFinancialPeriod")
    body = body_json()
    require_fields(body, ["branch_id", "charge_type", "amount_cents"])
    branch = get_or_404(db.branches, body["branch_id"], "Branch")
    if period.get("branch_id") != branch["id"]:
        raise err("ERR_NOT_FOUND", "Period does not belong to the given branch.")
    charge_type = require_enum(body, "charge_type", CHARGE_TYPES)
    amount = body["amount_cents"]
    if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
        raise err("ERR_INVALID_REQUEST", "amount_cents must be a positive integer.")
    if period.get("status") == "FINALIZED":
        raise err("ERR_PERIOD_FINALIZED", "Charges may not post to a FINALIZED period.")
    charge = stamp_new({
        "branch_id": branch["id"],
        "period_id": period["id"],
        "charge_type": charge_type,
        "amount_cents": amount,
        "status": "POSTED",
    })
    db.charges[charge["id"]] = charge
    # recompute period aggregates while OPEN or CLOSED (provisional variant)
    recompute_period(period)
    touch(period)
    return success_object(charge, 201)


@bp.route(f"{PERIODS}/<pid>/charges", methods=["GET"])
def list_period_charges(pid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin", "Advisor"})
    get_or_404(db.financial_periods, pid, "BranchFinancialPeriod")
    items = [c for c in db.charges.values() if c.get("period_id") == pid]
    items = sort_by_created_at(items)
    page, limit, offset, total, has_more = paginate(items)
    return success_list(page, limit, offset, total, has_more)


@bp.route(f"{CHARGES}/<cid>/reverse", methods=["POST"])
def reverse_charge(cid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    charge = get_or_404(db.charges, cid, "BranchCharge")
    if charge.get("status") != "POSTED":
        raise err("ERR_INVALID_STATE", "Charge is not POSTED.")
    charge["status"] = "REVERSED"
    touch(charge)
    period = db.financial_periods.get(charge.get("period_id"))
    if period is not None and period.get("status") == "OPEN":
        # While the period is OPEN the provisional aggregates track the current
        # postings. Once CLOSED, the provisional snapshot taken at close is
        # frozen — a post-close correction (reverse, then re-post after a
        # reopen) must not move it; the correction is picked up by the final
        # variant at finalization instead. The reversal still bumps the parent
        # period's version.
        recompute_period(period)
    if period is not None and period.get("status") in ("OPEN", "CLOSED"):
        touch(period)
    return success_object(charge)


@bp.route(f"{PERIODS}/<pid>/close", methods=["POST"])
def close_period(pid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    period = get_or_404(db.financial_periods, pid, "BranchFinancialPeriod")
    if period.get("status") != "OPEN":
        raise err("ERR_INVALID_STATE", "Period is not OPEN.")
    end = parse_dt(period["period_end"], "period_end")
    if db.clock.now() < end:
        raise err("ERR_PERIOD_NOT_CLOSABLE", "The logical clock has not reached period_end.")
    recompute_period(period)
    period["deficit_carryforward_cents"] = (
        abs(period["net_profit_cents"]) if period["net_profit_cents"] < 0 else 0)
    period["status"] = "CLOSED"
    touch(period)
    return success_object(period)


@bp.route(f"{PERIODS}/<pid>/reopen", methods=["POST"])
def reopen_period(pid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    period = get_or_404(db.financial_periods, pid, "BranchFinancialPeriod")
    if period.get("status") != "CLOSED":
        raise err("ERR_INVALID_STATE", "Period is not CLOSED.")
    # only the branch's latest period may be reopened
    branch_periods = _periods_for_branch(period["branch_id"])
    if len(branch_periods) > 1:
        # latest = max by (period_start, period_end)
        others = [p for p in branch_periods if p["id"] != pid]
        latest = max(branch_periods, key=lambda p: (p["period_start"], p["period_end"]))
        if latest["id"] != pid:
            raise err("ERR_PERIOD_NOT_LATEST", "Only the branch's latest period may be reopened.")
    period["status"] = "OPEN"
    period["deficit_carryforward_cents"] = 0
    touch(period)
    return success_object(period)


@bp.route(f"{PERIODS}/<pid>/finalize", methods=["POST"])
def finalize_period(pid):
    user_id, role = auth_context()
    require_role(role, {"HomeOfficeAdmin"})
    period = get_or_404(db.financial_periods, pid, "BranchFinancialPeriod")
    if period.get("status") != "CLOSED":
        raise err("ERR_INVALID_STATE", "Period is not CLOSED.")
    # final variant: include all POSTED charges as of the finalize instant
    recompute_period(period)
    period["status"] = "FINALIZED"
    touch(period)
    # deficit carryover onto the next OPEN period of the branch
    if period["net_profit_cents"] < 0:
        amount = abs(period["net_profit_cents"])
        period["deficit_carryforward_cents"] = amount
        next_open = None
        for p in _periods_for_branch(period["branch_id"]):
            if p["id"] != pid and p.get("status") == "OPEN":
                if next_open is None or p["period_start"] < next_open["period_start"]:
                    next_open = p
        if next_open is not None:
            charge = stamp_new({
                "branch_id": period["branch_id"],
                "period_id": next_open["id"],
                "charge_type": "DEFICIT_CARRYOVER",
                "amount_cents": amount,
                "status": "POSTED",
            })
            db.charges[charge["id"]] = charge
            recompute_period(next_open)
            touch(next_open)
    # service tier recomputed (threshold trigger)
    branch = db.branches.get(period["branch_id"])
    if branch is not None:
        recompute_tier(branch)
        touch(branch)
    return success_object(period)
