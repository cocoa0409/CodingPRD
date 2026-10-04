"""Curtailment decision pipeline (PRD 3.5): propose, approve, reject, revise,
execute, reverse -- with OCC, segregation of duties, and the execute gates."""
from datetime import timedelta

from flask import Blueprint, g

from auth import require_roles
from constants import TRIGGER_TYPES
from db import STORE, bump, logical_clock, new_id, stamp_new
from envelope import ok_object
from errors import raise_err
from serializers import decision_json
from services.core import active_labor_agreement, coverage_sufficient
from services.decisions import compute_economics_snapshot
from util import D, as_datetime, as_enum, as_number, as_str, get_body, is_int, req

bp = Blueprint("decisions", __name__, url_prefix="/smelter-ops")


def get_decision_or_404(decision_id):
    d = STORE["curtailment_decisions"].get(decision_id)
    if d is None:
        raise_err("ERR_NOT_FOUND", "CurtailmentDecision not found.")
    return d


def _validate_plan_window(body):
    depth = as_number(req(body, "depth_pct"), "depth_pct")
    if not (D(depth) > 0 and D(depth) <= 100):
        raise_err("ERR_INVALID_REQUEST", "depth_pct must be in (0, 100].")
    planned_start = as_datetime(req(body, "planned_start"), "planned_start")
    planned_end = as_datetime(req(body, "planned_end"), "planned_end")
    if not planned_start < planned_end:
        raise_err(
            "ERR_INVALID_REQUEST", "planned_start must be strictly before planned_end."
        )
    return depth, planned_start, planned_end


@bp.post("/curtailment-decisions")
@require_roles("SmelterManager")
def create_decision():
    body = get_body()
    potline_id = as_str(req(body, "potline_id"), "potline_id")
    potline = STORE["potlines"].get(potline_id)
    if potline is None:
        raise_err("ERR_NOT_FOUND", "Potline not found.")
    expected = body.get("expected_potline_version")
    if expected is None or not is_int(expected):
        raise_err(
            "ERR_INVALID_REQUEST",
            "expected_potline_version is required and must be an integer.",
        )
    if expected != potline["version"]:
        raise_err(
            "ERR_STALE_VERSION",
            "expected_potline_version does not match the potline's current version.",
        )
    if potline["operating_status"] not in ("OPERATING", "CURTAILED"):
        raise_err(
            "ERR_POTLINE_INVALID_STATE",
            "A decision can only be proposed for an OPERATING or CURTAILED potline.",
        )
    trigger = as_enum(req(body, "trigger_type"), "trigger_type", TRIGGER_TYPES)
    depth, planned_start, planned_end = _validate_plan_window(body)
    snapshot = compute_economics_snapshot(potline)
    # Creating a new decision supersedes any prior ECONOMIC_REVIEW decision.
    for prior in STORE["curtailment_decisions"].values():
        if prior["potline_id"] == potline_id and prior["status"] == "ECONOMIC_REVIEW":
            prior["status"] = "SUPERSEDED"
            bump(prior)
    bump(potline)
    rec = stamp_new(
        {
            "id": new_id(),
            "potline_id": potline_id,
            "trigger_type": trigger,
            "depth_pct": depth,
            "planned_start": planned_start,
            "planned_end": planned_end,
            "status": "ECONOMIC_REVIEW",
            "economics_snapshot": snapshot,
            "proposed_by_user_id": g.user_id,
            "economic_reviewed_by_user_id": None,
            "approved_by_user_id": None,
            "approved_at": None,
            "executed_at": None,
        }
    )
    STORE["curtailment_decisions"][rec["id"]] = rec
    return ok_object(decision_json(rec), 201)


@bp.post("/curtailment-decisions/<decision_id>/economic-approve")
@require_roles("Controller")
def economic_approve(decision_id):
    d = get_decision_or_404(decision_id)
    if g.user_id == d["proposed_by_user_id"]:
        raise_err(
            "ERR_SEGREGATION_OF_DUTIES",
            "The economic reviewer must differ from the proposer.",
        )
    if d["status"] != "ECONOMIC_REVIEW":
        raise_err(
            "ERR_DECISION_INVALID_STATE",
            "economic-approve requires status ECONOMIC_REVIEW.",
        )
    d["economic_reviewed_by_user_id"] = g.user_id
    d["status"] = "LABOR_REVIEW"
    bump(d)
    return ok_object(decision_json(d))


@bp.post("/curtailment-decisions/<decision_id>/labor-approve")
@require_roles("VPOperations")
def labor_approve(decision_id):
    d = get_decision_or_404(decision_id)
    if g.user_id in (d["proposed_by_user_id"], d["economic_reviewed_by_user_id"]):
        raise_err(
            "ERR_SEGREGATION_OF_DUTIES",
            "The labor approver must differ from proposer and economic reviewer.",
        )
    if d["status"] != "LABOR_REVIEW":
        raise_err(
            "ERR_DECISION_INVALID_STATE",
            "labor-approve requires status LABOR_REVIEW.",
        )
    d["approved_by_user_id"] = g.user_id
    d["approved_at"] = logical_clock()
    d["status"] = "APPROVED"
    bump(d)
    return ok_object(decision_json(d))


@bp.post("/curtailment-decisions/<decision_id>/reject")
@require_roles("Controller", "VPOperations")
def reject_decision(decision_id):
    d = get_decision_or_404(decision_id)
    if d["status"] not in ("ECONOMIC_REVIEW", "LABOR_REVIEW"):
        raise_err(
            "ERR_DECISION_INVALID_STATE",
            "reject requires status ECONOMIC_REVIEW or LABOR_REVIEW.",
        )
    d["status"] = "REJECTED"
    bump(d)
    return ok_object(decision_json(d))


@bp.post("/curtailment-decisions/<decision_id>/revise")
@require_roles("SmelterManager")
def revise_decision(decision_id):
    d = get_decision_or_404(decision_id)
    if d["status"] != "REJECTED":
        raise_err(
            "ERR_DECISION_INVALID_STATE", "revise requires status REJECTED."
        )
    body = get_body()
    depth, planned_start, planned_end = _validate_plan_window(body)
    potline = STORE["potlines"].get(d["potline_id"])
    if potline is None:
        raise_err("ERR_NOT_FOUND", "Potline not found.")
    d["depth_pct"] = depth
    d["planned_start"] = planned_start
    d["planned_end"] = planned_end
    d["economics_snapshot"] = compute_economics_snapshot(potline)
    d["economic_reviewed_by_user_id"] = None
    d["status"] = "ECONOMIC_REVIEW"
    bump(d)
    return ok_object(decision_json(d))


@bp.post("/curtailment-decisions/<decision_id>/execute")
@require_roles("SmelterManager")
def execute_decision(decision_id):
    d = get_decision_or_404(decision_id)
    if d["status"] != "APPROVED":
        raise_err(
            "ERR_DECISION_INVALID_STATE", "execute requires status APPROVED."
        )
    potline = STORE["potlines"].get(d["potline_id"])
    if potline is None:
        raise_err("ERR_NOT_FOUND", "Potline not found.")
    if potline["operating_status"] not in ("OPERATING", "CURTAILED"):
        raise_err(
            "ERR_POTLINE_INVALID_STATE",
            "execute requires the potline to be OPERATING or CURTAILED.",
        )
    now = logical_clock()
    agreement = active_labor_agreement(potline["smelter_id"])
    # Evaluation order (PRD 2.7): notice period (rule 12) ahead of presence (13).
    if agreement is not None:
        notice_end = d["approved_at"] + timedelta(days=agreement["notice_period_days"])
        if now < notice_end:
            raise_err(
                "ERR_LABOR_NOTICE_PERIOD",
                "The labor notice period has not yet elapsed.",
            )
    else:
        raise_err(
            "ERR_LABOR_AGREEMENT_INACTIVE",
            "The smelter has no ACTIVE labor agreement.",
        )
    smelter = STORE["smelters"][potline["smelter_id"]]
    if not coverage_sufficient(smelter):
        raise_err(
            "ERR_HEDGE_COVERAGE_INSUFFICIENT",
            "Smelter hedge coverage is below the minimum.",
        )
    depth = D(d["depth_pct"])
    if potline["operating_status"] == "OPERATING":
        potline["curtailed_since"] = now
    potline["operating_status"] = "IDLE" if depth == 100 else "CURTAILED"
    potline["curtailment_depth_pct"] = d["depth_pct"]
    potline["active_decision_id"] = d["id"]
    bump(potline)
    d["executed_at"] = now
    d["status"] = "EXECUTED"
    bump(d)
    return ok_object(decision_json(d))


@bp.post("/curtailment-decisions/<decision_id>/reverse")
@require_roles("SmelterManager")
def reverse_decision(decision_id):
    d = get_decision_or_404(decision_id)
    if d["status"] != "EXECUTED":
        raise_err(
            "ERR_DECISION_INVALID_STATE", "reverse requires status EXECUTED."
        )
    potline = STORE["potlines"].get(d["potline_id"])
    if potline is None:
        raise_err("ERR_NOT_FOUND", "Potline not found.")
    if (
        potline["operating_status"] != "CURTAILED"
        or potline["active_decision_id"] != d["id"]
    ):
        raise_err(
            "ERR_DECISION_INVALID_STATE",
            "reverse requires the potline to be CURTAILED under this decision.",
        )
    potline["operating_status"] = "OPERATING"
    potline["curtailment_depth_pct"] = 0
    potline["curtailed_since"] = None
    potline["active_decision_id"] = None
    bump(potline)
    d["status"] = "REVERSED"
    bump(d)
    return ok_object(decision_json(d))
