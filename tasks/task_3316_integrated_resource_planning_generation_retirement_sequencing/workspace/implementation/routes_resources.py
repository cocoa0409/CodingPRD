"""Fleet Resource routes: register, retire, cancel-retirement, mothball."""

from flask import Blueprint, request

from calculations import (
    FUEL_TYPES, MIN_RETIREMENT_LEAD_YEARS, RESOURCE_TYPES,
)
from db import store
from errors import (
    ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_PLAN_NOT_DRAFT,
    ERR_PLAN_NOT_FOUND, ERR_REFERENTIAL_INTEGRITY, ERR_RESOURCE_NOT_FOUND,
    ERR_RETIREMENT_TOO_EARLY, raise_error,
)
from helpers import (
    body, get_int, get_num, get_str, paginate, parse_pagination,
    require_enum, require_fields, stamp_new, touch,
)
from middleware import require_roles
from response import success_list, success_object
from serializers import resource_view

bp = Blueprint("resources", __name__)

RESOURCE_READ_ROLES = ("UtilityPlanner", "Commissioner", "Intervener", "PlatformAdmin")


def get_resource_or_404(resource_id: str) -> dict:
    r = store.resources.get(resource_id)
    if r is None:
        raise_error(ERR_RESOURCE_NOT_FOUND, f"Resource {resource_id} not found")
    return r


@bp.route("/resources", methods=["POST"])
@require_roles("UtilityPlanner")
def create_resource(user_id, role):
    payload = body()
    require_fields(payload, "unit_name", "resource_type", "nameplate_mw",
                   "in_service_year", "fuel_type")
    unit_name = get_str(payload, "unit_name")
    rtype = require_enum(payload, "resource_type", RESOURCE_TYPES)
    nameplate = get_num(payload, "nameplate_mw")
    if nameplate <= 0:
        raise_error(ERR_INVALID_REQUEST, "nameplate_mw must be > 0")
    in_service_year = get_int(payload, "in_service_year")
    fuel_type = require_enum(payload, "fuel_type", FUEL_TYPES)
    if rtype in ("STORAGE", "DEMAND_RESPONSE") and fuel_type != "NONE":
        raise_error(ERR_INVALID_REQUEST,
                    "STORAGE and DEMAND_RESPONSE resources must use fuel_type NONE")
    r = stamp_new({
        "unit_name": unit_name,
        "resource_type": rtype,
        "nameplate_mw": nameplate,
        "in_service_year": in_service_year,
        "fuel_type": fuel_type,
        "status": "ACTIVE",
        "retirement_year": None,
        "decision_year": None,
        "plan_id": None,
    })
    store.resources[r["id"]] = r
    return success_object(resource_view(r), 201)


@bp.route("/resources", methods=["GET"])
@require_roles(*RESOURCE_READ_ROLES)
def list_resources(user_id, role):
    limit, offset = parse_pagination()
    args = request.args
    items = list(store.resources.values())
    if "status" in args:
        items = [r for r in items if r["status"] == args["status"]]
    if "resource_type" in args:
        items = [r for r in items if r["resource_type"] == args["resource_type"]]
    if "plan_id" in args:
        items = [r for r in items if r.get("plan_id") == args["plan_id"]]
    page, total = paginate(items, limit, offset)
    return success_list([resource_view(r) for r in page], limit, offset, total)


@bp.route("/resources/<resourceId>", methods=["GET"])
@require_roles(*RESOURCE_READ_ROLES)
def get_resource(user_id, role, resourceId):
    r = get_resource_or_404(resourceId)
    return success_object(resource_view(r), 200)


@bp.route("/resources/<resourceId>/retire", methods=["POST"])
@require_roles("UtilityPlanner")
def retire_resource(user_id, role, resourceId):
    r = get_resource_or_404(resourceId)
    payload = body()
    require_fields(payload, "retirement_year", "plan_id")
    retirement_year = get_int(payload, "retirement_year")
    plan_id = payload["plan_id"]
    if not isinstance(plan_id, str):
        raise_error(ERR_INVALID_REQUEST, "plan_id must be a string")
    plan = store.plans.get(plan_id)
    if plan is None:
        raise_error(ERR_PLAN_NOT_FOUND, f"Plan {plan_id} not found")
    # State gate (priority 5): resource must be ACTIVE.
    if r["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "Resource is not ACTIVE")
    # Temporal guard (priority 6): minimum retirement lead.
    clock_year = store.clock.year()
    if retirement_year < clock_year + MIN_RETIREMENT_LEAD_YEARS:
        raise_error(ERR_RETIREMENT_TOO_EARLY,
                    "retirement_year is less than the minimum lead time")
    # Plan gates: SUPERSEDED -> referential failure; otherwise must be DRAFT.
    if plan["status"] == "SUPERSEDED":
        raise_error(ERR_REFERENTIAL_INTEGRITY,
                    "retire plan_id references a SUPERSEDED plan")
    if plan["status"] != "DRAFT":
        raise_error(ERR_PLAN_NOT_DRAFT, "Deciding plan is not DRAFT")
    r["status"] = "DECIDED"
    r["retirement_year"] = retirement_year
    r["decision_year"] = clock_year
    r["plan_id"] = plan["id"]
    # Retire cascade: bump every portfolio of the plan; retire-flag snapshots
    # with forecast_year >= retirement_year.
    for pf in store.portfolios.values():
        if pf["plan_id"] != plan["id"]:
            continue
        touch(pf)
        for s in store.snapshots.values():
            if s["portfolio_id"] == pf["id"] and s["forecast_year"] >= retirement_year:
                s["retire_flagged"] = True
    touch(r)
    return success_object(resource_view(r), 200)


@bp.route("/resources/<resourceId>/cancel-retirement", methods=["POST"])
@require_roles("UtilityPlanner")
def cancel_retirement(user_id, role, resourceId):
    r = get_resource_or_404(resourceId)
    if r["status"] != "DECIDED":
        raise_error(ERR_INVALID_STATE, "Resource is not DECIDED")
    plan = store.plans.get(r.get("plan_id"))
    if plan is None or plan["status"] not in ("DRAFT", "REJECTED"):
        raise_error(ERR_PLAN_NOT_DRAFT,
                    "Cancellation requires the deciding plan to be DRAFT or REJECTED")
    former_plan_id = r["plan_id"]
    r["status"] = "ACTIVE"
    r["retirement_year"] = None
    r["decision_year"] = None
    r["plan_id"] = None
    # Cascade: bump every portfolio under the former deciding plan.
    for pf in store.portfolios.values():
        if pf["plan_id"] == former_plan_id:
            touch(pf)
    touch(r)
    return success_object(resource_view(r), 200)


@bp.route("/resources/<resourceId>/mothball", methods=["POST"])
@require_roles("UtilityPlanner")
def mothball_resource(user_id, role, resourceId):
    r = get_resource_or_404(resourceId)
    if r["status"] != "DECIDED":
        raise_error(ERR_INVALID_STATE, "Resource is not DECIDED")
    clock_year = store.clock.year()
    if r.get("retirement_year") is None or r["retirement_year"] > clock_year + 1:
        raise_error(ERR_INVALID_STATE,
                    "Mothball requires retirement within one year of the clock year")
    r["status"] = "MOTHBALLED"
    touch(r)
    return success_object(resource_view(r), 200)
