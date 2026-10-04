"""LaunchPhase: listing (phase_index ascending), revision PATCH (the
GATE_FAILED -> PENDING loop), and gate evaluation."""

from flask import Blueprint

import calc
import validation as V
from auth import (
    ALL_ROLES,
    ROLE_MANUFACTURER_PLANNER,
    authenticate,
    authorize,
    scope_plan,
)
from calc import D
from constants import DISTRIBUTION_SUM_MAX_PCT
from envelope import success, success_list
from errors import err
from launches import get_launch
from storage import STORE, public, touch

bp = Blueprint("phases", __name__)


def _resolve_launch_and_phase(launch_id, phase_id):
    """Left-to-right path validation (PRD §2.6)."""
    launch = get_launch(launch_id)
    if launch is None:
        err("ERR_RESOURCE_NOT_FOUND", "launch not found")
    if phase_id is None:
        return launch, None
    phase = STORE["phases"].get(phase_id)
    if phase is None or phase["launch_id"] != launch_id:
        err("ERR_RESOURCE_NOT_FOUND", "phase not found under this launch")
    return launch, phase


@bp.get("/jbp/launches/<launch_id>/phases")
def list_phases(launch_id):
    uid, role = authenticate()
    authorize(role, ALL_ROLES)
    limit, offset = V.pagination()
    launch = get_launch(launch_id)
    if launch is not None:
        scope_plan(uid, role, STORE["plans"].get(launch["plan_id"]))
    if launch is None:
        err("ERR_RESOURCE_NOT_FOUND", "launch not found")
    items = calc.phases_of_launch(launch_id)  # phase_index ascending
    total = len(items)
    page = items[offset : offset + limit]
    return success_list([public(p) for p in page], limit, offset, total)


@bp.patch("/jbp/launches/<launch_id>/phases/<phase_id>")
def patch_phase(launch_id, phase_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_MANUFACTURER_PLANNER])
    data = V.body()
    V.check_undeclared(data, {"distribution_target_pct", "capacity_cases", "trade_spend_cents"})
    new_dist = None
    new_capacity = None
    new_spend = None
    if "distribution_target_pct" in data:
        new_dist = V.as_num(data["distribution_target_pct"], "distribution_target_pct")
        if new_dist < 0 or new_dist > 100:
            err("ERR_VALIDATION", "distribution_target_pct must be in [0, 100]")
    if "capacity_cases" in data:
        new_capacity = V.as_int(data["capacity_cases"], "capacity_cases")
        if new_capacity < 0:
            err("ERR_VALIDATION", "capacity_cases must be >= 0")
    if "trade_spend_cents" in data:
        new_spend = V.as_int(data["trade_spend_cents"], "trade_spend_cents")
        if new_spend < 0:
            err("ERR_VALIDATION", "trade_spend_cents must be >= 0")
    launch, phase = _resolve_launch_and_phase(launch_id, phase_id)  # 6
    # priority 15: phase editable only from PENDING/GATE_FAILED on a PLANNING launch
    if launch["status"] != "PLANNING" or phase["status"] not in ("PENDING", "GATE_FAILED"):
        err("ERR_PHASE_LOCKED", "phase not editable (phase locked or launch not PLANNING)")
    phases = calc.phases_of_launch(launch_id)
    # priority 23: distribution sum cap (Decimal-exact for fractional targets)
    dist_sum = sum(
        D(new_dist if p["id"] == phase_id and new_dist is not None else p["distribution_target_pct"])
        for p in phases
    )
    if dist_sum > D(DISTRIBUTION_SUM_MAX_PCT):
        err("ERR_DISTRIBUTION_SUM_EXCEEDED", "distribution_target_pct sum would exceed 100")
    # priority 24: phase budget cap
    spend_sum = sum(
        new_spend if p["id"] == phase_id and new_spend is not None else p["trade_spend_cents"]
        for p in phases
    )
    if spend_sum > launch["total_trade_budget_cents"]:
        err("ERR_PHASE_BUDGET_EXCEEDED", "trade spend would exceed total_trade_budget_cents")
    if new_dist is not None:
        phase["distribution_target_pct"] = new_dist
    if new_capacity is not None:
        phase["capacity_cases"] = new_capacity
    if new_spend is not None:
        phase["trade_spend_cents"] = new_spend
    if phase["status"] == "GATE_FAILED":
        phase["status"] = "PENDING"
    touch(phase)
    calc.recompute_launch(launch)
    touch(launch)
    return success(public(phase))


@bp.post("/jbp/launches/<launch_id>/phases/<phase_id>/evaluate")
def evaluate_phase(launch_id, phase_id):
    _uid, role = authenticate()
    authorize(role, [ROLE_MANUFACTURER_PLANNER])
    launch, phase = _resolve_launch_and_phase(launch_id, phase_id)  # 6
    if phase["status"] != "PENDING":
        err("ERR_INVALID_STATE", "only a PENDING phase can be evaluated")  # 7
    if launch["status"] != "PLANNING":
        err("ERR_INVALID_STATE", "phase gates evaluate only while the launch is PLANNING")  # 7
    lower = [p for p in calc.phases_of_launch(launch_id) if p["phase_index"] < phase["phase_index"]]
    passes = (
        all(p["status"] == "GATE_PASSED" for p in lower)
        and phase["distribution_target_pct"] > 0
        and phase["capacity_cases"] > 0
    )
    phase["status"] = "GATE_PASSED" if passes else "GATE_FAILED"
    touch(phase)
    calc.recompute_launch(launch)
    touch(launch)
    return success(public(phase))
