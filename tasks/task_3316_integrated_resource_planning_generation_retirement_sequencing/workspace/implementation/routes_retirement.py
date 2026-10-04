"""RetirementAnalysis routes: create, finalize, reopen, reads."""

from flask import Blueprint, request

from calculations import compute_retirement_analysis
from db import store
from errors import (
    ERR_ANALYSIS_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
    ERR_PLAN_NOT_DRAFT, ERR_PLAN_NOT_FOUND, ERR_SNAPSHOT_NOT_FOUND,
    ERR_SNAPSHOT_PLAN_MISMATCH, raise_error,
)
from helpers import (
    body, paginate, parse_pagination, require_fields, stamp_new, touch,
)
from middleware import require_roles
from response import success_list, success_object
from routes_plans import get_plan_or_404
from routes_resources import RESOURCE_READ_ROLES, get_resource_or_404
from serializers import analysis_view

bp = Blueprint("retirement_analyses", __name__)


def get_analysis_or_404(analysis_id: str) -> dict:
    a = store.retirement_analyses.get(analysis_id)
    if a is None:
        raise_error(ERR_ANALYSIS_NOT_FOUND, f"Analysis {analysis_id} not found")
    return a


@bp.route("/resources/<resourceId>/retirement-analyses", methods=["POST"])
@require_roles("UtilityPlanner")
def create_analysis(user_id, role, resourceId):
    r = get_resource_or_404(resourceId)
    payload = body()
    require_fields(payload, "plan_id", "snapshot_id")
    plan_id = payload["plan_id"]
    snapshot_id = payload["snapshot_id"]
    if not isinstance(plan_id, str) or not isinstance(snapshot_id, str):
        raise_error(ERR_INVALID_REQUEST, "plan_id and snapshot_id must be strings")
    plan = store.plans.get(plan_id)
    if plan is None:
        raise_error(ERR_PLAN_NOT_FOUND, f"Plan {plan_id} not found")
    snapshot = store.snapshots.get(snapshot_id)
    if snapshot is None:
        raise_error(ERR_SNAPSHOT_NOT_FOUND, f"Snapshot {snapshot_id} not found")
    # Referential check (priority 8): snapshot must belong to a portfolio of
    # the same plan as the analysis.
    portfolio = store.portfolios.get(snapshot["portfolio_id"])
    if portfolio is None or portfolio["plan_id"] != plan["id"]:
        raise_error(ERR_SNAPSHOT_PLAN_MISMATCH,
                    "Snapshot belongs to a portfolio of a different plan")
    decision_year = store.clock.year()
    computed = compute_retirement_analysis(r, snapshot, decision_year)
    a = stamp_new({
        "resource_id": r["id"],
        "plan_id": plan["id"],
        "snapshot_id": snapshot["id"],
        **computed,
        "status": "DRAFT",
    })
    store.retirement_analyses[a["id"]] = a
    return success_object(analysis_view(a), 201)


@bp.route("/resources/<resourceId>/retirement-analyses", methods=["GET"])
@require_roles("UtilityPlanner", "Commissioner", "PlatformAdmin")
def list_resource_analyses(user_id, role, resourceId):
    r = get_resource_or_404(resourceId)
    limit, offset = parse_pagination()
    items = [a for a in store.retirement_analyses.values() if a["resource_id"] == r["id"]]
    if "plan_id" in request.args:
        items = [a for a in items if a["plan_id"] == request.args["plan_id"]]
    if "snapshot_id" in request.args:
        items = [a for a in items if a["snapshot_id"] == request.args["snapshot_id"]]
    page, total = paginate(items, limit, offset)
    return success_list([analysis_view(a) for a in page], limit, offset, total)


@bp.route("/retirement-analyses/<analysisId>", methods=["GET"])
@require_roles("UtilityPlanner", "Commissioner", "PlatformAdmin")
def get_analysis(user_id, role, analysisId):
    a = get_analysis_or_404(analysisId)
    return success_object(analysis_view(a), 200)


@bp.route("/plans/<planId>/retirement-analyses", methods=["GET"])
@require_roles("UtilityPlanner", "Commissioner", "PlatformAdmin")
def list_plan_analyses(user_id, role, planId):
    plan = get_plan_or_404(planId)
    limit, offset = parse_pagination()
    items = [a for a in store.retirement_analyses.values() if a["plan_id"] == plan["id"]]
    if "snapshot_id" in request.args:
        items = [a for a in items if a["snapshot_id"] == request.args["snapshot_id"]]
    page, total = paginate(items, limit, offset)
    return success_list([analysis_view(a) for a in page], limit, offset, total)


@bp.route("/retirement-analyses", methods=["GET"])
@require_roles("UtilityPlanner", "Commissioner", "PlatformAdmin")
def list_analyses_flat(user_id, role):
    limit, offset = parse_pagination()
    items = list(store.retirement_analyses.values())
    args = request.args
    if "resource_id" in args:
        items = [a for a in items if a["resource_id"] == args["resource_id"]]
    if "plan_id" in args:
        items = [a for a in items if a["plan_id"] == args["plan_id"]]
    if "snapshot_id" in args:
        items = [a for a in items if a["snapshot_id"] == args["snapshot_id"]]
    page, total = paginate(items, limit, offset)
    return success_list([analysis_view(a) for a in page], limit, offset, total)


@bp.route("/retirement-analyses/<analysisId>/finalize", methods=["POST"])
@require_roles("UtilityPlanner")
def finalize_analysis(user_id, role, analysisId):
    a = get_analysis_or_404(analysisId)
    if a["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "Analysis is not DRAFT")
    a["status"] = "FINAL"
    touch(a)
    return success_object(analysis_view(a), 200)


@bp.route("/retirement-analyses/<analysisId>/reopen", methods=["POST"])
@require_roles("UtilityPlanner")
def reopen_analysis(user_id, role, analysisId):
    a = get_analysis_or_404(analysisId)
    if a["status"] != "FINAL":
        raise_error(ERR_INVALID_STATE, "Analysis is not FINAL")
    plan = store.plans.get(a["plan_id"])
    if plan is None or plan["status"] != "DRAFT":
        raise_error(ERR_PLAN_NOT_DRAFT, "Analysis plan is not DRAFT")
    r = store.resources.get(a["resource_id"])
    snapshot = store.snapshots.get(a["snapshot_id"])
    computed = compute_retirement_analysis(r, snapshot, store.clock.year())
    a.update(computed)
    a["status"] = "DRAFT"
    touch(a)
    return success_object(analysis_view(a), 200)
