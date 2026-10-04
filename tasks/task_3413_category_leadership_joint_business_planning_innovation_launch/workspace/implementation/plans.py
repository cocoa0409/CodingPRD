"""JointBusinessPlan: create/list/read, negotiate, decide, activate.

Covers the negotiation state machine (PROPOSED <-> COUNTERED, bounded at 6
rounds with error+auto-EXPIRE coupling), acceptance/rejection with the mover
mapping, and activation which creates the plan's single TradeFund.
"""

from flask import Blueprint, request

import calc
import clock
import validation as V
from auth import (
    ALL_ROLES,
    ROLE_MANUFACTURER_PLANNER,
    ROLE_RETAILER_BUYER,
    authenticate,
    authorize,
    rb_can_see,
    scope_plan,
)
from constants import (
    EVENT_SPLIT_MIN_PCT,
    FISCAL_YEAR_MAX,
    FISCAL_YEAR_MIN,
    FUND_ACCRUAL_RATE_MAX_PCT,
    GROWTH_TARGET_MAX_PCT,
    GROWTH_TARGET_MIN_PCT,
    MAX_NEGOTIATION_ROUNDS,
    PLAN_TERMINAL,
)
from envelope import success, success_list
from errors import err
from storage import STORE, by_seq, new_id, public, stamp_new, touch
from timeutil import fmt_logical

bp = Blueprint("plans", __name__)


def get_plan(plan_id):
    return STORE["plans"].get(plan_id)


def plan_or_404(plan_id):
    plan = get_plan(plan_id)
    if plan is None:
        err("ERR_PLAN_NOT_FOUND", "plan not found")
    return plan


@bp.post("/jbp/plans")
def create_plan():
    _uid, role = authenticate()
    authorize(role, [ROLE_MANUFACTURER_PLANNER])
    data = V.body()
    V.check_undeclared(
        data,
        {
            "retailer_id",
            "category_id",
            "fiscal_year",
            "growth_target_pct",
            "weekly_baseline_cases",
            "avg_unit_net_price_cents",
        },
    )
    retailer_id = V.as_str(V.require(data, "retailer_id"), "retailer_id")
    category_id = V.as_str(V.require(data, "category_id"), "category_id")
    fiscal_year = V.as_int(V.require(data, "fiscal_year"), "fiscal_year")
    if fiscal_year < FISCAL_YEAR_MIN or fiscal_year > FISCAL_YEAR_MAX:
        err("ERR_VALIDATION", "fiscal_year must be in [2026, 2030]")
    growth = V.as_num(V.require(data, "growth_target_pct"), "growth_target_pct")
    baseline = V.as_int(V.require(data, "weekly_baseline_cases"), "weekly_baseline_cases")
    if baseline <= 0:
        err("ERR_VALIDATION", "weekly_baseline_cases must be > 0")
    price = V.as_int(V.require(data, "avg_unit_net_price_cents"), "avg_unit_net_price_cents")
    if price <= 0:
        err("ERR_VALIDATION", "avg_unit_net_price_cents must be > 0")
    # priority 5: growth-target range
    if growth < GROWTH_TARGET_MIN_PCT or growth > GROWTH_TARGET_MAX_PCT:
        err("ERR_GROWTH_TARGET_OUT_OF_RANGE", "growth_target_pct outside [-20, 50]")
    # priority 6: body-referenced existence, left to right
    if retailer_id not in STORE["retailers"]:
        err("ERR_RETAILER_NOT_FOUND", "retailer_id does not resolve")
    if category_id not in STORE["categories"]:
        err("ERR_CATEGORY_NOT_FOUND", "category_id does not resolve")
    # priority 19: one live plan per (retailer, category, fiscal_year)
    for p in STORE["plans"].values():
        if (
            p["retailer_id"] == retailer_id
            and p["category_id"] == category_id
            and p["fiscal_year"] == fiscal_year
            and p["status"] not in PLAN_TERMINAL
        ):
            err("ERR_PLAN_ALREADY_EXISTS", "a live plan exists for this retailer/category/fiscal_year")
    plan = {
        "id": new_id(),
        "retailer_id": retailer_id,
        "category_id": category_id,
        "fiscal_year": fiscal_year,
        "growth_target_pct": growth,
        "weekly_baseline_cases": baseline,
        "avg_unit_net_price_cents": price,
        "status": "PROPOSED",
        "negotiation_round": 1,
        "committed_growth_pct": None,
        "activated_at": None,
    }
    stamp_new(plan)
    STORE["plans"][plan["id"]] = plan
    return success(public(plan), 201)


@bp.get("/jbp/plans/<plan_id>")
def read_plan(plan_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    plan = get_plan(plan_id)
    scope_plan(uid, role, plan)
    if plan is None:
        err("ERR_PLAN_NOT_FOUND", "plan not found")
    return success(public(plan))


@bp.get("/jbp/plans")
def list_plans():
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = V.pagination()
    items = by_seq(STORE["plans"].values())
    if role == ROLE_RETAILER_BUYER:
        items = [p for p in items if rb_can_see(uid, role, p)]
    f_retailer = request.args.get("retailer_id")
    if f_retailer is not None:
        items = [p for p in items if p["retailer_id"] == f_retailer]
    f_category = request.args.get("category_id")
    if f_category is not None:
        items = [p for p in items if p["category_id"] == f_category]
    f_status = request.args.get("status")
    if f_status is not None:
        items = [p for p in items if p["status"] == f_status]
    f_year = request.args.get("fiscal_year")
    if f_year is not None:
        try:
            fy = int(f_year)
        except (ValueError, TypeError):
            fy = None
        items = [p for p in items if fy is not None and p["fiscal_year"] == fy]
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([public(p) for p in page], limit, offset, total)


@bp.post("/jbp/plans/<plan_id>/negotiate")
def negotiate(plan_id):
    uid, role = authenticate()
    authorize(role, [ROLE_MANUFACTURER_PLANNER, ROLE_RETAILER_BUYER])
    plan = get_plan(plan_id)
    scope_plan(uid, role, plan)  # priority 3
    data = V.body()
    V.check_undeclared(data, {"growth_target_pct"})
    growth = V.as_num(V.require(data, "growth_target_pct"), "growth_target_pct")
    if growth < GROWTH_TARGET_MIN_PCT or growth > GROWTH_TARGET_MAX_PCT:
        err("ERR_GROWTH_TARGET_OUT_OF_RANGE", "growth_target_pct outside [-20, 50]")  # 5
    if plan is None:
        err("ERR_PLAN_NOT_FOUND", "plan not found")  # 6
    if plan["status"] in PLAN_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "plan is terminal")  # 8
    if plan["status"] not in ("PROPOSED", "COUNTERED"):
        err("ERR_INVALID_STATE", "plan is not in a negotiable state")  # 7
    # priority 9: mover mapping
    if plan["status"] == "PROPOSED" and role != ROLE_RETAILER_BUYER:
        err("ERR_NOT_YOUR_MOVE", "from PROPOSED only the RetailerBuyer may move")
    if plan["status"] == "COUNTERED" and role != ROLE_MANUFACTURER_PLANNER:
        err("ERR_NOT_YOUR_MOVE", "from COUNTERED only the ManufacturerPlanner may move")
    # priority 10: round budget; failure and auto-EXPIRE are inseparable
    if plan["negotiation_round"] >= MAX_NEGOTIATION_ROUNDS:
        plan["status"] = "EXPIRED"
        touch(plan)
        err("ERR_NEGOTIATION_ROUNDS_EXHAUSTED", "negotiation round budget spent; plan expired")
    plan["growth_target_pct"] = growth
    plan["negotiation_round"] += 1
    plan["status"] = "COUNTERED" if role == ROLE_RETAILER_BUYER else "PROPOSED"
    touch(plan)
    return success(public(plan))


@bp.post("/jbp/plans/<plan_id>/decide")
def decide_plan(plan_id):
    uid, role = authenticate()
    authorize(role, [ROLE_MANUFACTURER_PLANNER, ROLE_RETAILER_BUYER])
    plan = get_plan(plan_id)
    scope_plan(uid, role, plan)  # 3
    data = V.body()
    V.check_undeclared(data, {"decision"})
    decision = V.as_enum(V.require(data, "decision"), "decision", ["ACCEPT", "REJECT"])  # 4
    if plan is None:
        err("ERR_PLAN_NOT_FOUND", "plan not found")  # 6
    if plan["status"] in PLAN_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "plan is terminal")  # 8
    if plan["status"] not in ("PROPOSED", "COUNTERED"):
        err("ERR_INVALID_STATE", "no live offer to decide")  # 7
    if plan["status"] == "PROPOSED" and role != ROLE_RETAILER_BUYER:
        err("ERR_NOT_YOUR_MOVE", "from PROPOSED only the RetailerBuyer may decide")  # 9
    if plan["status"] == "COUNTERED" and role != ROLE_MANUFACTURER_PLANNER:
        err("ERR_NOT_YOUR_MOVE", "from COUNTERED only the ManufacturerPlanner may decide")  # 9
    plan["status"] = "ACCEPTED" if decision == "ACCEPT" else "REJECTED"
    touch(plan)
    return success(public(plan))


@bp.post("/jbp/plans/<plan_id>/activate")
def activate_plan(plan_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_MANUFACTURER_PLANNER])
    data = V.body()
    V.check_undeclared(data, {"accrual_rate_pct", "edlp_split_pct"})
    rate = V.as_num(V.require(data, "accrual_rate_pct"), "accrual_rate_pct")
    if rate <= 0 or rate > FUND_ACCRUAL_RATE_MAX_PCT:
        err("ERR_VALIDATION", "accrual_rate_pct must be in (0, 5]")
    split = V.as_int(V.require(data, "edlp_split_pct"), "edlp_split_pct")
    if split < 0:
        err("ERR_VALIDATION", "edlp_split_pct must be >= 0")
    plan = plan_or_404(plan_id)  # 6
    if plan["status"] in PLAN_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "plan is terminal")  # 8
    if plan["status"] != "ACCEPTED":
        err("ERR_INVALID_STATE", "only an ACCEPTED plan can be activated")  # 7
    retailer = STORE["retailers"].get(plan["retailer_id"])
    if retailer is None or retailer["status"] != "ACTIVE":
        err("ERR_INVALID_STATE", "retailer is not ACTIVE")  # 7 (suspended retailer)
    if split > 100 - EVENT_SPLIT_MIN_PCT:
        err("ERR_EVENT_SPLIT_TOO_LOW", "event share must be at least 20% (edlp_split_pct <= 80)")  # 34
    fund = {
        "id": new_id(),
        "plan_id": plan["id"],
        "accrual_rate_pct": rate,
        "edlp_split_pct": split,
        "edlp_accrued_cents": 0,
        "event_accrued_cents": 0,
        "edlp_cash_cents": 0,
        "event_cash_cents": 0,
        "event_reserved_cents": 0,
        "edlp_settled_cents": 0,
        "event_settled_cents": 0,
        "total_invoiced_cents": 0,
        "_periods": set(),
    }
    stamp_new(fund)
    STORE["funds"][fund["id"]] = fund
    plan["committed_growth_pct"] = plan["growth_target_pct"]
    plan["activated_at"] = fmt_logical(clock.now())
    plan["status"] = "ACTIVATED"
    touch(plan)
    return success(public(plan))


# Re-exported for sibling modules (funds list filter, cascades).
fund_of_plan = calc.fund_of_plan
