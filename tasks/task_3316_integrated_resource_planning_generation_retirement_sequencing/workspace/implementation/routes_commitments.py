"""ProcurementCommitment and PlanCondition routes."""

from flask import Blueprint, request

from calculations import committed_aggregate, waterfall_select
from db import store
from errors import (
    ERR_COMMITMENT_NOT_FOUND, ERR_COMMITMENT_NOT_ISSUABLE,
    ERR_CONDITION_ALREADY_DISCHARGED, ERR_CONDITION_NOT_FOUND, ERR_FORBIDDEN,
    ERR_INVALID_REQUEST, ERR_NAMEPLATE_EXCEEDED, ERR_NO_ELIGIBLE_CANDIDATE,
    ERR_PLAN_NOT_APPROVED, raise_error,
)
from helpers import (
    body, get_num, paginate, parse_pagination, require_enum, require_fields,
    stamp_new, touch,
)
from middleware import require_roles
from response import success_list, success_object
from routes_candidates import get_candidate_or_404
from routes_plans import get_plan_or_404
from serializers import commitment_view, condition_view

bp = Blueprint("commitments", __name__)

COMMITMENT_ROLES = ("UtilityPlanner", "Commissioner", "PlatformAdmin")
CONDITION_READ_ROLES = ("UtilityPlanner", "Commissioner", "Intervener", "PlatformAdmin")
SOLICITATION_TYPES = {"RFP", "SELF_BUILD"}


def get_commitment_or_404(commitment_id: str) -> dict:
    c = store.commitments.get(commitment_id)
    if c is None:
        raise_error(ERR_COMMITMENT_NOT_FOUND, f"Commitment {commitment_id} not found")
    return c


def get_condition_or_404(condition_id: str) -> dict:
    c = store.conditions.get(condition_id)
    if c is None:
        raise_error(ERR_CONDITION_NOT_FOUND, f"Condition {condition_id} not found")
    return c


@bp.route("/plans/<planId>/procurement-commitments", methods=["POST"])
@require_roles("UtilityPlanner")
def issue_commitment(user_id, role, planId):
    plan = get_plan_or_404(planId)
    payload = body()
    require_fields(payload, "committed_mw", "solicitation_type")
    committed = get_num(payload, "committed_mw")
    if committed <= 0:
        raise_error(ERR_INVALID_REQUEST, "committed_mw must be > 0")
    solicitation = require_enum(payload, "solicitation_type", SOLICITATION_TYPES)
    auto_select = payload.get("auto_select", False)
    if not isinstance(auto_select, bool):
        raise_error(ERR_INVALID_REQUEST, "auto_select must be a boolean")
    candidate_id = payload.get("candidate_id")
    condition_ids = payload.get("condition_discharge_ids", [])
    if not isinstance(condition_ids, list):
        raise_error(ERR_INVALID_REQUEST, "condition_discharge_ids must be an array")
    if not auto_select and not candidate_id:
        raise_error(ERR_INVALID_REQUEST,
                    "candidate_id is required unless auto_select is true")
    # State gate (priority 5).
    if plan["status"] not in ("APPROVED", "APPROVED_WITH_CONDITIONS"):
        raise_error(ERR_PLAN_NOT_APPROVED, "Plan is not approved")
    # Existence (priority 3): every listed condition id must exist and belong
    # to this plan (missing or cross-plan -> ERR_CONDITION_NOT_FOUND, 404).
    conditions = []
    for cid in condition_ids:
        cond = store.conditions.get(cid)
        if cond is None or cond["plan_id"] != plan["id"]:
            raise_error(ERR_CONDITION_NOT_FOUND,
                        f"Condition {cid} not found for this plan")
        conditions.append(cond)
    # Candidate resolution.
    if auto_select:
        candidate = waterfall_select(committed, store.clock.year())
    else:
        candidate = get_candidate_or_404(candidate_id)
        remaining = candidate["nameplate_mw"] - committed_aggregate(candidate["id"])
        if committed > remaining:
            if remaining <= 0:
                raise_error(ERR_NO_ELIGIBLE_CANDIDATE,
                            "Candidate has no remaining uncommitted nameplate")
            raise_error(ERR_NAMEPLATE_EXCEEDED,
                        "Aggregate committed MW would exceed candidate nameplate")
    discharge_ids = [c["id"] for c in conditions if c["status"] == "OPEN"]
    c = stamp_new({
        "plan_id": plan["id"],
        "candidate_id": candidate["id"],
        "committed_mw": committed,
        "solicitation_type": solicitation,
        "created_by_user_id": user_id,
        "condition_discharge_ids": discharge_ids,
        "status": "ISSUED",
    })
    store.commitments[c["id"]] = c
    return success_object(commitment_view(c), 201)


@bp.route("/plans/<planId>/procurement-commitments", methods=["GET"])
@require_roles(*COMMITMENT_ROLES)
def list_plan_commitments(user_id, role, planId):
    plan = get_plan_or_404(planId)
    limit, offset = parse_pagination()
    items = [c for c in store.commitments.values() if c["plan_id"] == plan["id"]]
    if "status" in request.args:
        items = [c for c in items if c["status"] == request.args["status"]]
    page, total = paginate(items, limit, offset)
    return success_list([commitment_view(c) for c in page], limit, offset, total)


@bp.route("/procurement-commitments/<commitmentId>", methods=["GET"])
@require_roles(*COMMITMENT_ROLES)
def get_commitment(user_id, role, commitmentId):
    c = get_commitment_or_404(commitmentId)
    return success_object(commitment_view(c), 200)


@bp.route("/procurement-commitments", methods=["GET"])
@require_roles(*COMMITMENT_ROLES)
def list_commitments_flat(user_id, role):
    limit, offset = parse_pagination()
    items = list(store.commitments.values())
    args = request.args
    if "plan_id" in args:
        items = [c for c in items if c["plan_id"] == args["plan_id"]]
    if "candidate_id" in args:
        items = [c for c in items if c["candidate_id"] == args["candidate_id"]]
    if "status" in args:
        items = [c for c in items if c["status"] == args["status"]]
    page, total = paginate(items, limit, offset)
    return success_list([commitment_view(c) for c in page], limit, offset, total)


@bp.route("/procurement-commitments/<commitmentId>/award", methods=["POST"])
@require_roles("Commissioner")
def award_commitment(user_id, role, commitmentId):
    c = get_commitment_or_404(commitmentId)
    plan = store.plans.get(c["plan_id"])
    # State gates (priority 5).
    if plan is None or plan["status"] not in ("APPROVED", "APPROVED_WITH_CONDITIONS"):
        raise_error(ERR_PLAN_NOT_APPROVED, "Plan is not approved")
    if c["status"] != "ISSUED":
        raise_error(ERR_COMMITMENT_NOT_ISSUABLE, "Commitment is not ISSUED")
    # Segregation of duties: issuer cannot award their own commitment.
    if c["created_by_user_id"] == user_id:
        raise_error(ERR_FORBIDDEN,
                    "The issuing planner cannot award their own commitment")
    c["status"] = "AWARDED"
    for cid in c.get("condition_discharge_ids", []):
        cond = store.conditions.get(cid)
        if cond is not None and cond["status"] == "OPEN":
            cond["status"] = "DISCHARGED"
            touch(cond)
    touch(c)
    return success_object(commitment_view(c), 200)


@bp.route("/procurement-commitments/<commitmentId>/cancel", methods=["POST"])
@require_roles("UtilityPlanner")
def cancel_commitment(user_id, role, commitmentId):
    c = get_commitment_or_404(commitmentId)
    if c["status"] != "ISSUED":
        raise_error(ERR_COMMITMENT_NOT_ISSUABLE, "Commitment is not ISSUED")
    for cid in c.get("condition_discharge_ids", []):
        cond = store.conditions.get(cid)
        if cond is not None and cond["status"] != "OPEN":
            raise_error(ERR_CONDITION_ALREADY_DISCHARGED,
                        "A listed condition is already DISCHARGED")
    c["status"] = "CANCELLED"
    touch(c)
    return success_object(commitment_view(c), 200)


# --- PlanCondition reads ------------------------------------------------------

@bp.route("/plans/<planId>/conditions", methods=["GET"])
@require_roles(*CONDITION_READ_ROLES)
def list_plan_conditions(user_id, role, planId):
    plan = get_plan_or_404(planId)
    limit, offset = parse_pagination()
    items = [c for c in store.conditions.values() if c["plan_id"] == plan["id"]]
    if "status" in request.args:
        items = [c for c in items if c["status"] == request.args["status"]]
    page, total = paginate(items, limit, offset)
    return success_list([condition_view(c) for c in page], limit, offset, total)


@bp.route("/conditions", methods=["GET"])
@require_roles(*CONDITION_READ_ROLES)
def list_conditions_flat(user_id, role):
    limit, offset = parse_pagination()
    items = list(store.conditions.values())
    if "plan_id" in request.args:
        items = [c for c in items if c["plan_id"] == request.args["plan_id"]]
    page, total = paginate(items, limit, offset)
    return success_list([condition_view(c) for c in page], limit, offset, total)


@bp.route("/conditions/<conditionId>", methods=["GET"])
@require_roles(*CONDITION_READ_ROLES)
def get_condition(user_id, role, conditionId):
    c = get_condition_or_404(conditionId)
    return success_object(condition_view(c), 200)
