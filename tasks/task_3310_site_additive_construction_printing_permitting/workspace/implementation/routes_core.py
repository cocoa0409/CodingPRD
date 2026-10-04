"""Clock, jurisdiction and community-deployment routes."""
from flask import Blueprint, request, jsonify

from db import store, now, set_clock, fmt_dt, stamp_created, touch, parse_dt
from errors import raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE
from middleware import require_roles, parse_pagination
from validate import body_dict, req_str, req_int, req_bool, req_dt, req_enum
from response import success_object, success_list
import services

bp = Blueprint("core", __name__)


@bp.post("/construction/_clock/set_current_utc")
def set_clock_route():
    require_roles("PlatformAdmin")
    body = body_dict(request.get_json(silent=True))
    value = req_dt(body, "current_utc")
    new_now = set_clock(value)
    services.lazy_eval_all()
    return success_object({"current_utc": fmt_dt(new_now)})


# --- Jurisdictions ---

@bp.post("/construction/jurisdictions")
def create_jurisdiction():
    require_roles("PlatformAdmin")
    body = body_dict(request.get_json(silent=True))
    code = req_str(body, "code")
    name = req_str(body, "name")
    ppp = req_bool(body, "permits_prescriptive_printed_path")
    am_days = req_int(body, "alternative_means_review_days", minimum=1)
    station = req_str(body, "weather_station_id")
    if any(j["code"] == code for j in store.jurisdictions.values()):
        raise_err(ERR_INVALID_REQUEST, "jurisdiction code must be unique")
    jur = stamp_created({
        "code": code,
        "name": name,
        "permits_prescriptive_printed_path": ppp,
        "alternative_means_review_days": am_days,
        "weather_station_id": station,
        "status": "ACTIVE",
    })
    store.jurisdictions[jur["id"]] = jur
    return success_object(jur, status=201)


@bp.get("/construction/jurisdictions/<jid>/sites")
def list_jurisdiction_sites(jid):
    require_roles("PlatformAdmin", "SiteManager", "PermitCoordinator", "JurisdictionReviewer")
    if jid not in store.jurisdictions:
        raise_err(ERR_NOT_FOUND, "jurisdiction not found")
    limit, offset = parse_pagination()
    sites = [s for s in store.sites.values() if s["jurisdiction_id"] == jid]
    status_filter = request.args.get("status")
    if status_filter:
        sites = [s for s in sites if s["status"] == status_filter]
    sites.sort(key=lambda s: s["created_at"])
    total = len(sites)
    page = sites[offset:offset + limit]
    return success_list(page, limit, offset, total)


# --- Community deployments ---

@bp.post("/construction/community-deployments")
def create_deployment():
    require_roles("PlatformAdmin")
    body = body_dict(request.get_json(silent=True))
    name = req_str(body, "name")
    jurisdiction_id = req_str(body, "jurisdiction_id")
    plan_id = req_str(body, "plan_id")
    count = req_int(body, "planned_unit_count", minimum=2)
    if jurisdiction_id not in store.jurisdictions:
        raise_err(ERR_NOT_FOUND, "jurisdiction not found")
    if plan_id not in store.plans:
        raise_err(ERR_NOT_FOUND, "plan not found")
    dep = stamp_created({
        "name": name,
        "jurisdiction_id": jurisdiction_id,
        "plan_id": plan_id,
        "status": "PLANNING",
        "planned_unit_count": count,
        "completed_unit_count": 0,
        "learning_curve_baseline_minutes": None,
        "learning_curve_factor": None,
        "learning_curve_variant": "FORWARD_LOOKING",
    })
    store.deployments[dep["id"]] = dep
    return success_object(dep, status=201)


@bp.get("/construction/community-deployments/<dep_id>")
def get_deployment(dep_id):
    require_roles("PlatformAdmin", "SiteManager", "Engineer")
    dep = store.deployments.get(dep_id)
    if dep is None:
        raise_err(ERR_NOT_FOUND, "deployment not found")
    return success_object(dep)


@bp.post("/construction/community-deployments/<dep_id>/activate")
def activate_deployment(dep_id):
    require_roles("PlatformAdmin")
    dep = store.deployments.get(dep_id)
    if dep is None:
        raise_err(ERR_NOT_FOUND, "deployment not found")
    if dep["status"] != "PLANNING":
        raise_err(ERR_INVALID_STATE, "deployment is not in PLANNING")
    plan = store.plans.get(dep["plan_id"])
    if plan is None or plan["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, "plan must be APPROVED to activate deployment")
    dep["status"] = "ACTIVE"
    touch(dep)
    return success_object(dep)


@bp.post("/construction/community-deployments/<dep_id>/set-learning-variant")
def set_learning_variant(dep_id):
    require_roles("PlatformAdmin")
    dep = store.deployments.get(dep_id)
    if dep is None:
        raise_err(ERR_NOT_FOUND, "deployment not found")
    body = body_dict(request.get_json(silent=True))
    variant = req_enum(body, "learning_curve_variant", {"FORWARD_LOOKING", "CHRONOLOGICAL"})
    dep["learning_curve_variant"] = variant
    services.recompute_learning_curve(dep)
    touch(dep)
    return success_object(dep)
