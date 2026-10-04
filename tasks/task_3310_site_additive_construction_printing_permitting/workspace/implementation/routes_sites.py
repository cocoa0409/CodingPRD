"""Site lifecycle routes: register, get, action (POUR/CONFIRM_CURE/COMPLETE/SUSPEND)."""
from datetime import timedelta

from flask import Blueprint, request

from db import store, now, fmt_dt, stamp_created, touch, parse_dt
from errors import (
    raise_err,
    ERR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_INVALID_REQUEST,
    ERR_POSTURE_BLOCKED,
    ERR_FOUNDATION_NOT_CURED,
    ERR_FORBIDDEN,
)
from middleware import require_roles, get_role, parse_pagination
from validate import body_dict, req_str, opt_str, req_enum, req_int
from response import success_object, success_list
import services

bp = Blueprint("sites", __name__)

SOIL_CLASSES = {"A", "B", "C", "D"}
FOUNDATION_KINDS = {"SLAB", "PIER_AND_BEAM", "FOOTING"}


@bp.post("/construction/sites")
def create_site():
    require_roles("SiteManager")
    body = body_dict(request.get_json(silent=True))
    jurisdiction_id = req_str(body, "jurisdiction_id")
    address = req_str(body, "address")
    dep_id = opt_str(body, "community_deployment_id")
    soil = req_enum(body, "soil_class", SOIL_CLASSES)
    foundation = req_enum(body, "foundation_kind", FOUNDATION_KINDS)
    if jurisdiction_id not in store.jurisdictions:
        raise_err(ERR_NOT_FOUND, "jurisdiction not found")
    if dep_id is not None and dep_id not in store.deployments:
        raise_err(ERR_NOT_FOUND, "community deployment not found")
    site = stamp_created({
        "jurisdiction_id": jurisdiction_id,
        "address": address,
        "community_deployment_id": dep_id,
        "soil_class": soil,
        "foundation_kind": foundation,
        "status": "REGISTERED",
        "foundation_poured_at": None,
        "foundation_cured_at": None,
        "posture": "OPERATING",
    })
    store.sites[site["id"]] = site
    return success_object(site, status=201)


@bp.get("/construction/sites/<site_id>")
def get_site(site_id):
    require_roles(
        "PlatformAdmin", "SiteManager", "PermitCoordinator", "JurisdictionReviewer",
        "Engineer", "PrintOperator", "QualityInspector", "TradeContractor",
    )
    site = store.sites.get(site_id)
    if site is None:
        raise_err(ERR_NOT_FOUND, "site not found")
    services.lazy_eval_site(site)
    return success_object(site)


@bp.post("/construction/sites/<site_id>/action")
def site_action(site_id):
    role = require_roles("SiteManager", "PlatformAdmin")
    site = store.sites.get(site_id)
    if site is None:
        raise_err(ERR_NOT_FOUND, "site not found")
    services.lazy_eval_site(site)
    body = body_dict(request.get_json(silent=True))
    action = body.get("action")
    if not isinstance(action, str):
        raise_err(ERR_INVALID_REQUEST, "action is required")

    if action == "SUSPEND":
        if role != "PlatformAdmin":
            raise_err(ERR_FORBIDDEN, "only PlatformAdmin may suspend a site")
        return _suspend(site)
    if action == "POUR_FOUNDATION":
        return _pour(site)
    if action == "CONFIRM_CURE":
        return _confirm_cure(site)
    if action == "COMPLETE":
        return _complete(site)
    raise_err(ERR_INVALID_REQUEST, "unknown action %s" % action)


def _pour(site):
    # priority 6: posture gate for pours
    if site["posture"] == "STOP":
        raise_err(ERR_POSTURE_BLOCKED, "site posture is STOP")
    if site["status"] != "REGISTERED":
        raise_err(ERR_INVALID_STATE, "site must be REGISTERED to pour foundation")
    poured = now()
    site["foundation_poured_at"] = fmt_dt(poured)
    site["foundation_cured_at"] = fmt_dt(poured + timedelta(hours=services.FOUNDATION_CURE_HOURS))
    site["status"] = "FOUNDATION_POURED"
    touch(site)
    services.recompute_posture(site["id"])
    return success_object(site)


def _confirm_cure(site):
    if site["status"] != "FOUNDATION_POURED":
        raise_err(ERR_INVALID_STATE, "site must be FOUNDATION_POURED to confirm cure")
    if now() < parse_dt(site["foundation_cured_at"]):
        raise_err(ERR_FOUNDATION_NOT_CURED, "foundation cure window has not elapsed")
    site["status"] = "FOUNDATION_CURED"
    touch(site)
    services.recompute_posture(site["id"])
    return success_object(site)


def _complete(site):
    if site["status"] != "SITE_READY":
        raise_err(ERR_INVALID_STATE, "site must be SITE_READY to complete")
    jobs = services.site_jobs(site["id"])
    if not all(j["status"] == "COMPLETED" for j in jobs):
        raise_err(ERR_INVALID_STATE, "every print job must be COMPLETED")
    trades = [t for t in store.trade_tasks.values() if t["site_id"] == site["id"]]
    if not all(t["status"] == "COMPLETED" for t in trades):
        raise_err(ERR_INVALID_STATE, "every trade task must be COMPLETED")
    job_ids = {j["id"] for j in jobs}
    for i in store.inspections.values():
        if i["print_job_id"] in job_ids and i["disposition"] in ("PENDING", "REPAIR_REQUIRED"):
            raise_err(ERR_INVALID_STATE, "open layer inspections block site completion")
    site["status"] = "COMPLETED"
    touch(site)
    dep_id = site.get("community_deployment_id")
    if dep_id:
        dep = store.deployments.get(dep_id)
        if dep is not None:
            services.recompute_learning_curve(dep)
            touch(dep)
    services.recompute_posture(site["id"])
    return success_object(site)


def _suspend(site):
    if site["status"] in ("SUSPENDED", "COMPLETED"):
        raise_err(ERR_INVALID_STATE, "site cannot be suspended from %s" % site["status"])
    jobs = services.site_jobs(site["id"])
    if any(j["status"] in ("PRINTING", "PAUSED") for j in jobs):
        raise_err(ERR_INVALID_STATE, "cannot suspend with an active print job")
    for j in jobs:
        if j["status"] in ("SCHEDULED", "READY_TO_PRINT"):
            j["status"] = "CANCELLED"
            touch(j)
    for t in store.trade_tasks.values():
        if t["site_id"] == site["id"] and t["status"] in ("PLANNED", "READY"):
            t["status"] = "CANCELLED"
            touch(t)
    for p in store.permits.values():
        if p["site_id"] == site["id"] and p["status"] in ("DRAFT", "SUBMITTED", "AM_REVIEW"):
            p["status"] = "WITHDRAWN"
            touch(p)
    site["status"] = "SUSPENDED"
    touch(site)
    services.recompute_posture(site["id"])
    return success_object(site)
