"""Mine plan submission and approval endpoints (PRD section 3.7)."""
from datetime import timedelta

from flask import Blueprint, g, request

import clock
import store
from constants import (
    BUSINESS_READ_ROLES,
    PLAN_REVISION_DAYS,
    PLAN_TYPES,
    ROLE_DISTRICT_MANAGER,
    ROLE_OPERATOR_REP,
    UNDERGROUND_ONLY_PLAN_TYPES,
)
from envelope import list_response, ok_object
from errors import (
    ApiError,
    ERR_INVALID_STATE,
    ERR_OPERATOR_MISMATCH,
    ERR_PLAN_TYPE_NOT_REQUIRED,
    ERR_STALE_VERSION,
)
from serialize import mine_plan as ser_plan
from validate import get_or_404, parse_body, require_roles

bp = Blueprint("plans", __name__, url_prefix="/msha")


@bp.route("/mines/<mineId>/mine-plans", methods=["POST"])
def submit_plan(mineId):
    require_roles(ROLE_OPERATOR_REP)
    body = parse_body({
        "plan_type": ("enum", True, PLAN_TYPES),
        "document_ref": ("str", True),
    })
    mine = get_or_404(store.mines, mineId, "mine")
    if g.uid != mine["operator_id"]:
        raise ApiError(ERR_OPERATOR_MISMATCH, "X-User-ID must be the operator of this mine")
    if body["plan_type"] in UNDERGROUND_ONLY_PLAN_TYPES and mine["mine_type"] != "UNDERGROUND":
        raise ApiError(
            ERR_PLAN_TYPE_NOT_REQUIRED,
            "{} plans apply only to UNDERGROUND mines".format(body["plan_type"]),
        )
    prior_revisions = [
        p["revision_no"]
        for p in store.plans.values()
        if p["mine_id"] == mineId and p["plan_type"] == body["plan_type"]
    ]
    entity = store.new_entity(store.plans, {
        "mine_id": mineId,
        "plan_type": body["plan_type"],
        "revision_no": 1 + (max(prior_revisions) if prior_revisions else 0),
        "document_ref": body["document_ref"],
        "submitted_at": clock.now(),
        "supersedes_plan_id": None,
        "next_revision_due_at": None,
        "approved_at": None,
        "rejection_reason": None,
        "status": "SUBMITTED",
    })
    return ok_object(ser_plan(entity), 201)


@bp.route("/mine-plans/<planId>", methods=["GET"])
def get_plan(planId):
    require_roles(*BUSINESS_READ_ROLES)
    return ok_object(ser_plan(get_or_404(store.plans, planId, "mine plan")))


@bp.route("/mine-plans", methods=["GET"])
def list_plans():
    require_roles(*BUSINESS_READ_ROLES)
    items = list(store.plans.values())
    for param in ("mine_id", "supersedes_plan_id", "plan_type", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [p for p in items if p.get(param) is not None and p[param] == value]
    return list_response(items, ser_plan)


@bp.route("/mine-plans/<planId>/approve", methods=["POST"])
def approve_plan(planId):
    require_roles(ROLE_DISTRICT_MANAGER)
    body = parse_body({"expected_mine_version": ("int", True)})
    plan = get_or_404(store.plans, planId, "mine plan")
    mine = store.mines.get(plan["mine_id"])
    # Tier 5 OCC precedes the tier 7 state check.
    if body["expected_mine_version"] != mine["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            "expected_mine_version does not match the mine's current version",
        )
    if plan["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "approval requires SUBMITTED status")
    prior_approved = [
        p
        for p in store.plans.values()
        if p["mine_id"] == mine["id"]
        and p["plan_type"] == plan["plan_type"]
        and p["status"] == "APPROVED"
        and p["id"] != plan["id"]
    ]
    for prior in prior_approved:
        prior["status"] = "SUPERSEDED"
        store.touch(prior)
    plan["supersedes_plan_id"] = prior_approved[0]["id"] if prior_approved else None
    now = clock.now()
    plan["approved_at"] = now
    plan["next_revision_due_at"] = now + timedelta(days=PLAN_REVISION_DAYS)
    plan["status"] = "APPROVED"
    store.touch(plan)
    store.touch(mine)
    return ok_object(ser_plan(plan))


@bp.route("/mine-plans/<planId>/reject", methods=["POST"])
def reject_plan(planId):
    require_roles(ROLE_DISTRICT_MANAGER)
    body = parse_body({"rejection_reason": ("str", True)})
    plan = get_or_404(store.plans, planId, "mine plan")
    if plan["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, "rejection requires SUBMITTED status")
    plan["rejection_reason"] = body["rejection_reason"]
    plan["status"] = "REJECTED"
    store.touch(plan)
    return ok_object(ser_plan(plan))
