"""Potline lifecycle: create, read, emergency curtail/restore, shutdown, child lists."""
from flask import Blueprint

from auth import require_roles
from constants import ROLES
from db import STORE, bump, logical_clock, new_id, stamp_new
from envelope import ok_list, ok_object
from errors import raise_err
from serializers import decision_json, potline_json, restart_plan_json
from services.core import covering_active_contract
from util import D, as_number, as_str, get_body, parse_pagination, req

bp = Blueprint("potlines", __name__, url_prefix="/smelter-ops")


def get_potline_or_404(potline_id):
    p = STORE["potlines"].get(potline_id)
    if p is None:
        raise_err("ERR_NOT_FOUND", "Potline not found.")
    return p


@bp.post("/potlines")
@require_roles("SmelterManager")
def create_potline():
    body = get_body()
    smelter_id = as_str(req(body, "smelter_id"), "smelter_id")
    if STORE["smelters"].get(smelter_id) is None:
        raise_err("ERR_NOT_FOUND", "Smelter not found.")
    line_code = as_str(req(body, "line_code"), "line_code")
    capacity = as_number(req(body, "capacity_tpd"), "capacity_tpd")
    if capacity <= 0:
        raise_err("ERR_INVALID_REQUEST", "capacity_tpd must be > 0.")
    amperage = as_number(req(body, "amperage_ka"), "amperage_ka")
    if amperage <= 0:
        raise_err("ERR_INVALID_REQUEST", "amperage_ka must be > 0.")
    if covering_active_contract(smelter_id) is None:
        raise_err(
            "ERR_NO_ACTIVE_POWER_CONTRACT",
            "Smelter has no ACTIVE power contract covering the current logical clock.",
        )
    rec = stamp_new(
        {
            "id": new_id(),
            "smelter_id": smelter_id,
            "line_code": line_code,
            "capacity_tpd": capacity,
            "amperage_ka": amperage,
            "operating_status": "OPERATING",
            "curtailment_depth_pct": 0,
            "curtailed_since": None,
            "last_full_shutdown_at": None,
            "active_decision_id": None,
        }
    )
    STORE["potlines"][rec["id"]] = rec
    return ok_object(potline_json(rec), 201)


@bp.get("/potlines/<potline_id>")
@require_roles(*ROLES)
def get_potline(potline_id):
    return ok_object(potline_json(get_potline_or_404(potline_id)))


@bp.post("/potlines/<potline_id>/curtail")
@require_roles("SmelterManager")
def curtail_potline(potline_id):
    p = get_potline_or_404(potline_id)
    status = p["operating_status"]
    if status not in ("OPERATING", "CURTAILED"):
        raise_err(
            "ERR_POTLINE_INVALID_STATE",
            "Potline cannot be curtailed from status %s." % status,
        )
    body = get_body()
    raw_depth = as_number(req(body, "depth_pct"), "depth_pct")
    depth = D(raw_depth)
    if depth < 0 or depth > 100:
        raise_err("ERR_CURTAILMENT_DEPTH_INVALID", "depth_pct must lie within [0, 100].")
    now = logical_clock()
    if status == "OPERATING":
        if depth == 0:
            raise_err(
                "ERR_CURTAILMENT_DEPTH_INVALID",
                "A depth_pct of 0 restores and is only valid from CURTAILED.",
            )
        p["curtailment_depth_pct"] = raw_depth
        p["curtailed_since"] = now
        p["active_decision_id"] = None
        p["operating_status"] = "IDLE" if depth == 100 else "CURTAILED"
    else:  # CURTAILED
        if depth == 0:
            if p["active_decision_id"] is not None:
                raise_err(
                    "ERR_CURTAILMENT_DEPTH_INVALID",
                    "Decision-linked curtailment must be reversed via the decision.",
                )
            p["operating_status"] = "OPERATING"
            p["curtailment_depth_pct"] = 0
            p["curtailed_since"] = None
        elif depth == 100:
            # Completing the idle leaves curtailed_since untouched: the downtime
            # clock runs continuously from the moment the line left OPERATING.
            p["operating_status"] = "IDLE"
            p["curtailment_depth_pct"] = raw_depth
        else:
            if depth <= D(p["curtailment_depth_pct"]):
                raise_err(
                    "ERR_CURTAILMENT_DEPTH_INVALID",
                    "A deepen must strictly exceed the current curtailment_depth_pct.",
                )
            p["curtailment_depth_pct"] = raw_depth
    bump(p)
    return ok_object(potline_json(p))


@bp.post("/potlines/<potline_id>/shutdown")
@require_roles("SmelterManager")
def shutdown_potline(potline_id):
    p = get_potline_or_404(potline_id)
    if p["operating_status"] != "IDLE":
        raise_err(
            "ERR_POTLINE_INVALID_STATE",
            "Only an IDLE potline can be shut down.",
        )
    decision = STORE["curtailment_decisions"].get(p["active_decision_id"] or "")
    if (
        decision is None
        or decision["status"] != "EXECUTED"
        or D(decision["depth_pct"]) != 100
    ):
        raise_err(
            "ERR_POTLINE_INVALID_STATE",
            "Shutdown requires an EXECUTED depth-100 decision driving the potline.",
        )
    p["operating_status"] = "SHUTDOWN"
    p["last_full_shutdown_at"] = logical_clock()
    bump(p)
    return ok_object(potline_json(p))


def _list_child(potline_id, store_key, serializer):
    get_potline_or_404(potline_id)
    limit, offset = parse_pagination()
    items = [r for r in STORE[store_key].values() if r.get("potline_id") == potline_id]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    page = items[offset : offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, len(items))


@bp.get("/potlines/<potline_id>/curtailment-decisions")
@require_roles(*ROLES)
def list_curtailment_decisions(potline_id):
    return _list_child(potline_id, "curtailment_decisions", decision_json)


@bp.get("/potlines/<potline_id>/restart-plans")
@require_roles(*ROLES)
def list_restart_plans(potline_id):
    return _list_child(potline_id, "restart_plans", restart_plan_json)
