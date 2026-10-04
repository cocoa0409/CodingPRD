"""Service-plan endpoints: monitoring, maintenance windows and hardware."""

from datetime import timedelta

from flask import Blueprint, request

import calc
import constants as C
import middleware
import store
from errors import (
    ERR_EXIT_WINDOW_CONFLICT, ERR_FOOTPRINT_EXCEEDED, ERR_INVALID_REQUEST,
    ERR_INVALID_STATE, ERR_PPA_NOT_FOUND, ERR_REFERENCE_NOT_FOUND,
    ERR_SITE_FROZEN, ERR_WINDOW_VIOLATION, ApiError,
)
from fields import Body

bp = Blueprint("service", __name__)


def load_ppa(ppa_id):
    ppa = store.get_ppa(ppa_id)
    if ppa is None:
        raise ApiError(ERR_PPA_NOT_FOUND, "no contract exists with that id", 404)
    return ppa


def load_plan(ppa, plan_id):
    plan = store.get_service_plan(plan_id)
    if plan is None or plan.get("ppa_id") != ppa["id"]:
        raise ApiError(ERR_REFERENCE_NOT_FOUND, "no service plan exists for that contract", 404)
    return plan


def open_plans(site):
    return [p for p in store.site_plans(site["id"])
            if p.get("lifecycle_state") in ("SERVICE_ACTIVE", "SERVICE_MAINTENANCE_WINDOW_OPEN")]


def windows_conflict(site, start, end, ignore_plan_id=None):
    """Closed-interval windows at one site must be separated by the gap."""
    if start is None or end is None:
        return False
    for plan in store.site_plans(site["id"]):
        if plan.get("id") == ignore_plan_id:
            continue
        if plan.get("lifecycle_state") == "SERVICE_ARCHIVED":
            continue
        if not plan.get("window_start_iso8601") or not plan.get("window_end_iso8601"):
            continue
        other_start = store.parse_dt(plan["window_start_iso8601"])
        other_end = store.parse_dt(plan["window_end_iso8601"])
        if start <= other_end + timedelta(days=C.MAINTENANCE_GAP_DAYS) \
                and other_start <= end + timedelta(days=C.MAINTENANCE_GAP_DAYS):
            return True
    return False


def refresh_plan(plan):
    """Recompute the plan's derived readings."""
    if plan.get("monitoring_degraded_at"):
        degraded = store.days_between(store.parse_dt(plan["monitoring_degraded_at"]), store.clock())
    else:
        degraded = 0
    plan["monitoring_degraded_days"] = degraded
    plan["dispatch_hold"] = degraded > C.MODULE_DISPATCH_HOLD_DAYS
    ppa = store.get_ppa(plan["ppa_id"])
    site = store.get_site(ppa["site_id"]) if ppa else None
    if site is None:
        plan["rollout_schedule_compliant"] = True
    else:
        compliant = True
        windows = []
        for other in open_plans(site):
            if other.get("window_start_iso8601") and other.get("window_end_iso8601"):
                windows.append((store.parse_dt(other["window_start_iso8601"]),
                                store.parse_dt(other["window_end_iso8601"])))
        windows.sort()
        for index in range(1, len(windows)):
            if windows[index][0] < windows[index - 1][1] + timedelta(days=C.MAINTENANCE_GAP_DAYS):
                compliant = False
                break
        plan["rollout_schedule_compliant"] = compliant
    return plan


@bp.route("/power/ppas/<ppa_id>/service-plans", methods=["POST"])
def create_service_plan(ppa_id):
    middleware.authenticate(request.headers, ("POST", "/power/ppas/{id}/service-plans"))
    ppa = load_ppa(ppa_id)
    site = store.get_site(ppa["site_id"])
    body = Body(request.get_json(silent=True))
    monitoring = body.req("remote_monitoring_status", "string", enum=C.MONITORING_STATUSES)
    radius = body.req("radius_buffer_m", "number")
    start_raw = body.opt("window_start_iso8601", "string")
    end_raw = body.opt("window_end_iso8601", "string")
    if (start_raw is None) != (end_raw is None):
        raise ApiError(ERR_INVALID_REQUEST,
                       "the window boundaries are supplied together or not at all", 400)

    start = store.parse_dt(start_raw) if start_raw else None
    end = store.parse_dt(end_raw) if end_raw else None
    if start is not None and end is not None and windows_conflict(site, start, end):
        raise ApiError(ERR_WINDOW_VIOLATION, "the window is too close to an open window", 422)
    if start is not None and end is not None and start >= end:
        raise ApiError(ERR_WINDOW_VIOLATION, "the window start is not before its end", 422)
    used = calc.site_clearance_used(site)
    if used + float(radius or 0) > float(site.get("clearance_zone_capacity") or 0):
        raise ApiError(ERR_FOOTPRINT_EXCEEDED, "the clearance zone is exhausted", 422)
    for pending in store.site_ppas(site["id"]):
        if pending.get("id") == ppa["id"] or pending.get("state") != "PPA_EXIT_PENDING":
            continue
        if start is None or end is None:
            continue
        cure_start = store.parse_dt(pending["state_entered_at"])
        cure_end = cure_start + timedelta(days=int(pending.get("customer_cure_deadline_days") or 0))
        if start < cure_end and cure_start < end:
            raise ApiError(ERR_EXIT_WINDOW_CONFLICT,
                           "the window overlaps a cure window at this site", 422)
    body.raise_if_invalid()

    plan = {
        "ppa_id": ppa["id"],
        "remote_monitoring_status": monitoring,
        "lifecycle_state": "SERVICE_PLAN_DRAFT",
        "module_replacement_stage": "REPLACEMENT_NONE",
        "radius_buffer_m": radius,
        "monitoring_degraded_at": None,
        "monitoring_degraded_days": 0,
        "rollout_schedule_compliant": True,
        "window_start_iso8601": start_raw,
        "window_end_iso8601": end_raw,
        "dispatch_hold": False,
    }
    store.create(store.service_plans, plan)
    calc.recompute_site(site)
    store.touch(ppa)
    store.touch(site)
    return middleware.ok(refresh_plan(plan), status=201)


@bp.route("/power/ppas/<ppa_id>/service-plans", methods=["GET"])
def list_service_plans(ppa_id):
    middleware.authenticate(request.headers, ("GET", "/power/ppas/{id}/service-plans"))
    ppa = load_ppa(ppa_id)
    rows = store.by_created(store.ppa_plans(ppa["id"]))
    wanted = request.args.get("lifecycle_state")
    if wanted:
        rows = [p for p in rows if p.get("lifecycle_state") == wanted]
    page, meta = store.paginate(rows, request.args)
    for plan in page:
        refresh_plan(plan)
    return middleware.ok_list(page, meta)


@bp.route("/power/ppas/<ppa_id>/service-plans/<plan_id>", methods=["GET"])
def get_service_plan(ppa_id, plan_id):
    middleware.authenticate(request.headers, ("GET", "/power/ppas/{id}/service-plans/{id}"))
    ppa = load_ppa(ppa_id)
    plan = load_plan(ppa, plan_id)
    return middleware.ok(refresh_plan(plan))


@bp.route("/power/ppas/<ppa_id>/service-plans/<plan_id>/schedule-replacement", methods=["POST"])
def schedule_replacement(ppa_id, plan_id):
    middleware.authenticate(
        request.headers, ("POST", "/power/ppas/{id}/service-plans/{id}/schedule-replacement"))
    ppa = load_ppa(ppa_id)
    plan = load_plan(ppa, plan_id)
    site = store.get_site(ppa["site_id"])
    if site is None or site.get("status") != "SITE_ACTIVE":
        raise ApiError(ERR_SITE_FROZEN, "site is suspended", 409)
    if ppa.get("state") != "PPA_ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "contract is not active", 409)
    if plan.get("lifecycle_state") != "SERVICE_ACTIVE":
        raise ApiError(ERR_INVALID_STATE, "service plan is not active", 409)
    if plan.get("module_replacement_stage") != "REPLACEMENT_NONE":
        raise ApiError(ERR_INVALID_STATE, "a replacement is already staged", 409)
    refresh_plan(plan)
    if int(plan.get("monitoring_degraded_days") or 0) > C.MODULE_DISPATCH_HOLD_DAYS:
        raise ApiError(ERR_INVALID_STATE, "the monitoring link is degraded beyond tolerance", 409)
    plan["module_replacement_stage"] = "REPLACEMENT_SCHEDULED"
    store.touch(plan)
    store.touch(ppa)
    return middleware.ok(refresh_plan(plan))


@bp.route("/power/ppas/<ppa_id>/service-plans/<plan_id>/dispatch-module-replacement",
           methods=["POST"])
def dispatch_module_replacement(ppa_id, plan_id):
    middleware.authenticate(
        request.headers,
        ("POST", "/power/ppas/{id}/service-plans/{id}/dispatch-module-replacement"))
    ppa = load_ppa(ppa_id)
    plan = load_plan(ppa, plan_id)
    if plan.get("module_replacement_stage") != "REPLACEMENT_SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, "no replacement is scheduled", 409)
    if ppa.get("assigned_service_plan_id") != plan["id"]:
        raise ApiError(ERR_INVALID_STATE, "the plan is not the contract's assigned plan", 409)
    refresh_plan(plan)
    if plan.get("dispatch_hold"):
        raise ApiError(ERR_INVALID_STATE, "dispatch is held", 409)
    plan["module_replacement_stage"] = "REPLACEMENT_DISPATCHED"
    plan["_replacement_revert_at"] = store.ts(
        store.clock() + timedelta(hours=C.MODULE_REPLACEMENT_REVERT_HOURS))
    store.touch(plan)
    store.touch(ppa)
    return middleware.ok(refresh_plan(plan))
