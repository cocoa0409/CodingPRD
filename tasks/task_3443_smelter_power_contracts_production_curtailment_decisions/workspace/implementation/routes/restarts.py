"""Restart plans: create, start, complete (PRD 3.6)."""
from flask import Blueprint

from auth import require_roles
from db import STORE, bump, logical_clock, new_id, stamp_new
from envelope import ok_object
from errors import raise_err
from serializers import restart_plan_json
from services.core import active_spl_permit_exists, potline_restart_class
from services.restart import actual_cost, estimated_cost, whole_days_between
from util import as_datetime, as_str, get_body, req

bp = Blueprint("restarts", __name__, url_prefix="/smelter-ops")


def get_plan_or_404(plan_id):
    r = STORE["restart_plans"].get(plan_id)
    if r is None:
        raise_err("ERR_NOT_FOUND", "RestartPlan not found.")
    return r


def _downtime_origin(potline):
    if potline["operating_status"] == "SHUTDOWN":
        return potline["last_full_shutdown_at"]
    return potline["curtailed_since"]


@bp.post("/restart-plans")
@require_roles("SmelterManager")
def create_restart_plan():
    body = get_body()
    potline_id = as_str(req(body, "potline_id"), "potline_id")
    potline = STORE["potlines"].get(potline_id)
    if potline is None:
        raise_err("ERR_NOT_FOUND", "Potline not found.")
    if potline["operating_status"] not in ("IDLE", "SHUTDOWN"):
        raise_err(
            "ERR_POTLINE_INVALID_STATE",
            "A restart plan requires an IDLE or SHUTDOWN potline.",
        )
    for r in STORE["restart_plans"].values():
        if r["potline_id"] == potline_id and r["status"] in ("PLANNED", "IN_PROGRESS"):
            raise_err(
                "ERR_RESTART_PLAN_EXISTS",
                "A live restart plan already exists for this potline.",
            )
    planned_restart_at = as_datetime(
        req(body, "planned_restart_at"), "planned_restart_at"
    )
    if planned_restart_at < logical_clock():
        raise_err(
            "ERR_INVALID_REQUEST",
            "planned_restart_at must not lie before the current logical clock.",
        )
    cost_class = potline_restart_class(potline)
    idle_days = whole_days_between(_downtime_origin(potline), planned_restart_at)
    estimate = estimated_cost(cost_class, potline["capacity_tpd"], idle_days)
    rec = stamp_new(
        {
            "id": new_id(),
            "potline_id": potline_id,
            "planned_restart_at": planned_restart_at,
            "status": "PLANNED",
            "restart_cost_class": cost_class,
            "estimated_cost_usd": estimate,
            "actual_cost_usd": None,
            "_started_at": None,
            "_origin": None,
        }
    )
    STORE["restart_plans"][rec["id"]] = rec
    return ok_object(restart_plan_json(rec), 201)


@bp.post("/restart-plans/<plan_id>/start")
@require_roles("SmelterManager")
def start_restart_plan(plan_id):
    r = get_plan_or_404(plan_id)
    if r["status"] != "PLANNED":
        raise_err(
            "ERR_RESTART_PLAN_INVALID_STATE", "start requires status PLANNED."
        )
    potline = STORE["potlines"].get(r["potline_id"])
    if potline is None:
        raise_err("ERR_NOT_FOUND", "Potline not found.")
    if potline["operating_status"] not in ("IDLE", "SHUTDOWN"):
        raise_err(
            "ERR_POTLINE_INVALID_STATE",
            "start requires the potline to be IDLE or SHUTDOWN.",
        )
    if not active_spl_permit_exists(potline["smelter_id"]):
        raise_err(
            "ERR_PERMIT_NOT_ACTIVE",
            "An ACTIVE SPL_DISPOSAL permit is required to start a restart.",
        )
    r["_started_at"] = logical_clock()
    r["_origin"] = _downtime_origin(potline)
    potline["operating_status"] = "RESTARTING"
    bump(potline)
    r["status"] = "IN_PROGRESS"
    bump(r)
    return ok_object(restart_plan_json(r))


@bp.post("/restart-plans/<plan_id>/complete")
@require_roles("SmelterManager")
def complete_restart_plan(plan_id):
    r = get_plan_or_404(plan_id)
    if r["status"] != "IN_PROGRESS":
        raise_err(
            "ERR_RESTART_PLAN_INVALID_STATE", "complete requires status IN_PROGRESS."
        )
    potline = STORE["potlines"].get(r["potline_id"])
    if potline is None:
        raise_err("ERR_NOT_FOUND", "Potline not found.")
    if potline["operating_status"] != "RESTARTING":
        raise_err(
            "ERR_POTLINE_INVALID_STATE",
            "complete requires the potline to be RESTARTING.",
        )
    now = logical_clock()
    realized_idle_days = whole_days_between(r["_origin"], r["_started_at"])
    realized_restart_days = whole_days_between(r["_started_at"], now)
    r["actual_cost_usd"] = actual_cost(
        r["restart_cost_class"],
        potline["capacity_tpd"],
        realized_idle_days,
        realized_restart_days,
    )
    potline["operating_status"] = "OPERATING"
    potline["curtailment_depth_pct"] = 0
    potline["curtailed_since"] = None
    potline["active_decision_id"] = None
    bump(potline)
    r["status"] = "COMPLETED"
    bump(r)
    return ok_object(restart_plan_json(r))
