"""InnovationLaunch: creation (auto-creating exactly 4 PENDING phases),
listing, reading, and execution (phase gates checked before the calendar)."""

from flask import Blueprint, request

import calc
import clock
import validation as V
from auth import (
    ALL_ROLES,
    ROLE_MANUFACTURER_PLANNER,
    authenticate,
    authorize,
    scope_plan,
)
from constants import (
    LAUNCH_MIN_GAP_DAYS,
    LAUNCH_TERMINAL,
    PHASE_COUNT,
    PHASE_TYPES_BY_INDEX,
)
from envelope import success, success_list
from errors import err
from plans import plan_or_404
from storage import STORE, by_seq, new_id, public, stamp_new, touch
from timeutil import fmt_logical

bp = Blueprint("launches", __name__)


def get_launch(launch_id):
    return STORE["launches"].get(launch_id)


def launch_or_404(launch_id):
    launch = get_launch(launch_id)
    if launch is None:
        err("ERR_RESOURCE_NOT_FOUND", "launch not found")
    return launch


@bp.post("/jbp/plans/<plan_id>/launches")
def create_launch(plan_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_MANUFACTURER_PLANNER])
    data = V.body()
    V.check_undeclared(
        data, {"product_name", "pack_family", "launch_date", "total_trade_budget_cents"}
    )
    product_name = V.as_str(V.require(data, "product_name"), "product_name")
    pack_family = V.as_str(V.require(data, "pack_family"), "pack_family")
    launch_date = V.as_dt(V.require(data, "launch_date"), "launch_date")
    budget = V.as_int(V.require(data, "total_trade_budget_cents"), "total_trade_budget_cents")
    if budget <= 0:
        err("ERR_VALIDATION", "total_trade_budget_cents must be > 0")
    plan = plan_or_404(plan_id)  # 6
    if plan["status"] != "ACTIVATED":
        err("ERR_PLAN_NOT_ACTIVATED", "launch create requires an ACTIVATED plan")  # 12
    # priority 29: fiscal-year fit
    if launch_date.year != plan["fiscal_year"]:
        err("ERR_LAUNCH_OUTSIDE_FISCAL_YEAR", "launch_date year must equal plan fiscal_year")
    # priority 30: separation from other PLANNING/LAUNCHED launches of the plan
    gap_seconds = LAUNCH_MIN_GAP_DAYS * 86400
    for other in STORE["launches"].values():
        if other["plan_id"] != plan_id or other["status"] not in ("PLANNING", "LAUNCHED"):
            continue
        if abs((launch_date - other["_launch_date_dt"]).total_seconds()) < gap_seconds:
            err("ERR_LAUNCH_TOO_CLOSE", "launch_date within 84 days of another live launch")
    launch = {
        "id": new_id(),
        "plan_id": plan_id,
        "product_name": product_name,
        "pack_family": pack_family,
        "launch_date": fmt_logical(launch_date),
        "total_trade_budget_cents": budget,
        "status": "PLANNING",
        "budget_remaining_cents": budget,
        "projected_distribution_weighted_pct": 0,
        "projected_distribution_committed_pct": 0,
        "launched_at": None,
        "_launch_date_dt": launch_date,
    }
    stamp_new(launch)
    STORE["launches"][launch["id"]] = launch
    # exactly PHASE_COUNT LaunchPhase children, all PENDING, all numerics 0
    for idx in range(1, PHASE_COUNT + 1):
        phase = {
            "id": new_id(),
            "launch_id": launch["id"],
            "phase_index": idx,
            "phase_type": PHASE_TYPES_BY_INDEX[idx],
            "distribution_target_pct": 0,
            "capacity_cases": 0,
            "trade_spend_cents": 0,
            "status": "PENDING",
        }
        stamp_new(phase)
        STORE["phases"][phase["id"]] = phase
    return success(public(launch), 201)


@bp.get("/jbp/plans/<plan_id>/launches")
def list_launches(plan_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = V.pagination()
    plan = STORE["plans"].get(plan_id)
    scope_plan(uid, role, plan)
    if plan is None:
        err("ERR_PLAN_NOT_FOUND", "plan not found")
    items = [l for l in by_seq(STORE["launches"].values()) if l["plan_id"] == plan_id]
    f_status = request.args.get("status")
    if f_status is not None:
        items = [l for l in items if l["status"] == f_status]
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([public(l) for l in page], limit, offset, total)


@bp.get("/jbp/launches/<launch_id>")
def read_launch(launch_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    launch = get_launch(launch_id)
    if launch is not None:
        scope_plan(uid, role, STORE["plans"].get(launch["plan_id"]))
    if launch is None:
        err("ERR_RESOURCE_NOT_FOUND", "launch not found")
    return success(public(launch))


@bp.post("/jbp/launches/<launch_id>/launch")
def execute_launch(launch_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_MANUFACTURER_PLANNER])
    launch = get_launch(launch_id)
    if launch is None:
        err("ERR_RESOURCE_NOT_FOUND", "launch not found")  # 6
    if launch["status"] in LAUNCH_TERMINAL:
        err("ERR_ALREADY_TERMINAL", "launch is terminal")  # 8
    if launch["status"] != "PLANNING":
        err("ERR_INVALID_STATE", "only a PLANNING launch can be executed")  # 7
    # priority 14 (state check) BEFORE priority 31 (calendar check)
    phases = calc.phases_of_launch(launch["id"])
    if any(p["status"] != "GATE_PASSED" for p in phases):
        err("ERR_PHASE_GATES_INCOMPLETE", "every phase must stand at GATE_PASSED")
    if clock.now() < launch["_launch_date_dt"]:
        err("ERR_LAUNCH_DATE_NOT_REACHED", "logical clock has not reached launch_date")
    launch["status"] = "LAUNCHED"
    launch["launched_at"] = fmt_logical(clock.now())
    touch(launch)
    return success(public(launch))
