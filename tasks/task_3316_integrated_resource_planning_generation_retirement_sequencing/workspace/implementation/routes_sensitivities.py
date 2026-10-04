"""SensitivityAnalysis routes."""

from flask import Blueprint, request

from calculations import compute_sensitivity
from db import store
from errors import (
    ERR_INVALID_REQUEST, ERR_SNAPSHOT_NOT_FOUND, ERR_SNAPSHOT_PLAN_MISMATCH,
    raise_error,
)
from errors import ApiError
from helpers import (
    body, get_num, paginate, parse_pagination, require_enum, require_fields,
    stamp_new,
)
from middleware import require_roles
from response import success_list, success_object
from routes_plans import get_plan_or_404
from serializers import sensitivity_view

bp = Blueprint("sensitivities", __name__)

SENSITIVITY_ROLES = ("UtilityPlanner", "Commissioner", "PlatformAdmin")
DIMENSIONS = {"FUEL_PRICE", "POLICY", "TECHNOLOGY_COST"}
SCORING_VARIANTS = {"COST_PLUS", "MARKET"}
ERR_SENSITIVITY_NOT_FOUND = ("ERR_ANALYSIS_NOT_FOUND", 404)  # no dedicated id in catalog


def get_sensitivity_or_404(sensitivity_id: str) -> dict:
    s = store.sensitivities.get(sensitivity_id)
    if s is None:
        raise_error(ERR_SENSITIVITY_NOT_FOUND, f"Sensitivity {sensitivity_id} not found")
    return s


@bp.route("/plans/<planId>/sensitivities", methods=["POST"])
@require_roles("UtilityPlanner")
def create_sensitivity(user_id, role, planId):
    plan = get_plan_or_404(planId)
    payload = body()
    require_fields(payload, "snapshot_id", "dimension", "delta_pct")
    snapshot_id = payload["snapshot_id"]
    if not isinstance(snapshot_id, str):
        raise_error(ERR_INVALID_REQUEST, "snapshot_id must be a string")
    dimension = require_enum(payload, "dimension", DIMENSIONS)
    delta = get_num(payload, "delta_pct")
    if delta < -0.5 or delta > 0.5:
        raise_error(ERR_INVALID_REQUEST, "delta_pct must be within [-0.50, +0.50]")
    scoring_variant = payload.get("scoring_variant", "COST_PLUS")
    if scoring_variant not in SCORING_VARIANTS:
        raise_error(ERR_INVALID_REQUEST, "scoring_variant must be COST_PLUS or MARKET")
    snapshot = store.snapshots.get(snapshot_id)
    if snapshot is None:
        raise_error(ERR_SNAPSHOT_NOT_FOUND, f"Snapshot {snapshot_id} not found")
    # Referential: snapshot must belong to a portfolio of this plan.
    portfolio = store.portfolios.get(snapshot["portfolio_id"])
    if portfolio is None or portfolio["plan_id"] != plan["id"]:
        raise_error(ERR_SNAPSHOT_PLAN_MISMATCH,
                    "Snapshot belongs to a different plan")
    computed = compute_sensitivity(snapshot, dimension, delta, scoring_variant)
    s = stamp_new({
        "plan_id": plan["id"],
        "snapshot_id": snapshot["id"],
        "dimension": dimension,
        "delta_pct": delta,
        "scoring_variant": scoring_variant,
        **computed,
    })
    store.sensitivities[s["id"]] = s
    return success_object(sensitivity_view(s), 201)


@bp.route("/plans/<planId>/sensitivities", methods=["GET"])
@require_roles(*SENSITIVITY_ROLES)
def list_plan_sensitivities(user_id, role, planId):
    plan = get_plan_or_404(planId)
    limit, offset = parse_pagination()
    items = [s for s in store.sensitivities.values() if s["plan_id"] == plan["id"]]
    args = request.args
    if "dimension" in args:
        items = [s for s in items if s["dimension"] == args["dimension"]]
    if "snapshot_id" in args:
        items = [s for s in items if s["snapshot_id"] == args["snapshot_id"]]
    page, total = paginate(items, limit, offset)
    return success_list([sensitivity_view(s) for s in page], limit, offset, total)


@bp.route("/sensitivities", methods=["GET"])
@require_roles(*SENSITIVITY_ROLES)
def list_sensitivities_flat(user_id, role):
    limit, offset = parse_pagination()
    items = list(store.sensitivities.values())
    args = request.args
    if "plan_id" in args:
        items = [s for s in items if s["plan_id"] == args["plan_id"]]
    if "snapshot_id" in args:
        items = [s for s in items if s["snapshot_id"] == args["snapshot_id"]]
    page, total = paginate(items, limit, offset)
    return success_list([sensitivity_view(s) for s in page], limit, offset, total)


@bp.route("/sensitivities/<sensitivityId>", methods=["GET"])
@require_roles(*SENSITIVITY_ROLES)
def get_sensitivity(user_id, role, sensitivityId):
    s = get_sensitivity_or_404(sensitivity_id)
    return success_object(sensitivity_view(s), 200)
