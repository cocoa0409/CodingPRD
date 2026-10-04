"""Project routes: create/list/get/recompute-projection."""
from decimal import Decimal

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_roles, ALL_ROLES
from response import success_object, success_list
from services import compute_sizing, recompute_projection, recompute_augmentation_count
from util import (new_id, stamp_new, touch, req_string, req_enum, req_pos_number,
                  req_nonneg_int, opt_field, to_number, round2)

bp = Blueprint("projects", __name__)

MARKET_APPLICATIONS = {"ENERGY_ARBITRAGE", "FREQUENCY_REGULATION", "CAPACITY_FIRMING"}
DUTY_CYCLE_PROFILES = {"ONE_CYCLE_DAILY", "TWO_CYCLES_DAILY", "CONTINUOUS"}


def serialize_project(p):
    return dict(p)


def _paginate(items):
    args = request.args
    try:
        limit = int(args.get("limit", 10))
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


@bp.route("/projects", methods=["POST"])
@require_roles({"ProjectDeveloper"})
def create_project():
    body = request.get_json(silent=True) or {}
    name = req_string(body, "name")
    market = req_enum(body, "market_application", MARKET_APPLICATIONS)
    duty = req_enum(body, "duty_cycle_profile", DUTY_CYCLE_PROFILES)
    rated_power = req_pos_number(body, "rated_power_mw")
    rated_energy = req_pos_number(body, "rated_energy_mwh")
    budget = req_nonneg_int(body, "budget_cents")

    p = {
        "id": new_id(),
        "name": name,
        "market_application": market,
        "duty_cycle_profile": duty,
        "rated_power_mw": rated_power,
        "rated_energy_mwh": rated_energy,
        "budget_cents": budget,
        "commissioned_capacity_mwh": 0,
        "equivalent_cycles": 0,
        "projected_capacity_mwh": 0,
        "augmentation_count": 0,
    }
    stamp_new(p)
    compute_sizing(p)
    store.projects[p["id"]] = p
    return success_object(serialize_project(p), 201)


@bp.route("/projects", methods=["GET"])
@require_roles(set(ALL_ROLES))
def list_projects():
    limit, offset = _paginate(None)
    items = sorted(store.projects.values(), key=lambda x: (x["created_at"], x["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_project(p) for p in page], limit, offset, total)


@bp.route("/projects/<pid>", methods=["GET"])
@require_roles(set(ALL_ROLES))
def get_project(pid):
    p = store.projects.get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Project not found")
    return success_object(serialize_project(p))


@bp.route("/projects/<pid>/recompute-projection", methods=["POST"])
@require_roles({"ProjectDeveloper", "PerformanceEngineer"})
def recompute_project_projection(pid):
    p = store.projects.get(pid)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Project not found")
    body = request.get_json(silent=True) or {}
    cycles = body.get("equivalent_cycles")
    if isinstance(cycles, bool) or not isinstance(cycles, int) or cycles < 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "equivalent_cycles must be a non-negative integer")
    p["equivalent_cycles"] = cycles
    recompute_projection(p)
    touch(p)
    return success_object(serialize_project(p))
