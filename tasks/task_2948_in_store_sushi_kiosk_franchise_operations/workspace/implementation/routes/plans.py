"""Production plans -- PRD 3.4."""

from flask import Blueprint

import db
from core import LOCK
from errors import ApiError
from middleware import (ROLE_FRANCHISE_CHEF, ROLE_FRANCHISOR_OPS,
                        ROLE_HOST_STORE_MANAGER, ROLE_QUALITY_AUDITOR, authorize,
                        body, req_date, req_int, req_str)
from response import created, ok
from routes.base import fk_lookup, filters, kiosk_or_404, paginate, plan_or_404
from services import calc, domain

bp = Blueprint("plans", __name__)


def _scope_plan(actor, plan):
    """PRD 2.1 ownership for the two entity-backed roles."""
    kiosk = domain.kiosk_of_plan(plan)
    if actor.is_chef:
        chef = db.chefs.get(actor.user_id)
        if chef is None or chef["assigned_kiosk_id"] != plan["kiosk_id"]:
            raise ApiError("ERR_OWNERSHIP_MISMATCH")
    elif actor.is_manager:
        store = domain.store_of_kiosk(kiosk) if kiosk is not None else None
        if store is None or store["id"] != actor.user_id:
            raise ApiError("ERR_OWNERSHIP_MISMATCH")


@bp.post("/production-plans")
def create_plan():
    actor = authorize(ROLE_FRANCHISE_CHEF, ROLE_FRANCHISOR_OPS)
    payload = body()
    # Ownership (rung 3) is decidable from the body key alone, so it precedes
    # the existence rung for this endpoint.
    if actor.is_chef:
        chef = db.chefs.get(actor.user_id)
        if chef is None or chef["assigned_kiosk_id"] != payload.get("kiosk_id"):
            raise ApiError("ERR_OWNERSHIP_MISMATCH")
    kiosk = fk_lookup(payload, "kiosk_id", kiosk_or_404)
    req_str(payload, "kiosk_id")
    production_date = req_date(payload, "production_date")
    traffic_forecast = req_int(payload, "traffic_forecast", minimum=0)
    expected_version = req_int(payload, "expected_kiosk_version")

    with LOCK:
        if expected_version != kiosk["version"]:
            raise ApiError("ERR_STALE_KIOSK_VERSION")
        if kiosk["sanitation_posture"] == "LOCKDOWN":
            raise ApiError("ERR_KIOSK_POSTURE_LOCKDOWN")
        agreement = domain.agreement_of(kiosk)
        if (agreement is None
                or production_date < agreement["effective_from"]
                or production_date > agreement["effective_to"]):
            raise ApiError("ERR_PLAN_DATE_OUTSIDE_AGREEMENT")
        store = domain.store_of_agreement(agreement)

        superseded_id = None
        for prior in domain.plans_of_kiosk(kiosk["id"]):
            if prior["production_date"] == production_date \
                    and prior["status"] == "DRAFT":
                domain.void_plan(prior, "SUPERSEDED")
                superseded_id = prior["id"]

        allocation = calc.daily_production_allocation(
            traffic_forecast,
            store["refrigerated_case_capacity_packs"],
            store["refrigerated_case_linear_ft"],
            kiosk["certified_chef_count"],
            kiosk["sanitation_posture"])

        row = db.new_row(db.production_plans, {
            "kiosk_id": kiosk["id"],
            "production_date": production_date,
            "traffic_forecast": traffic_forecast,
            "status": "DRAFT",
            "planned_pack_count": allocation["planned_pack_count"],
            "planned_rice_kg": allocation["planned_rice_kg"],
            "posture_factor_applied": allocation["posture_factor_applied"],
            "binding_cap_source": allocation["binding_cap_source"],
            "actual_pack_count": 0,
            "forecast_variance_pct": None,
            "superseded_plan_id": superseded_id,
            "void_reason": None,
        })
        db.touch(kiosk)
    return created(db.public(row))


@bp.get("/production-plans/<plan_id>")
def get_plan(plan_id):
    actor = authorize(ROLE_FRANCHISOR_OPS, ROLE_HOST_STORE_MANAGER,
                      ROLE_FRANCHISE_CHEF, ROLE_QUALITY_AUDITOR)
    plan = plan_or_404(plan_id)
    _scope_plan(actor, plan)
    return ok(db.public(plan))


@bp.get("/production-plans")
def list_plans():
    actor = authorize(ROLE_FRANCHISOR_OPS, ROLE_HOST_STORE_MANAGER,
                      ROLE_FRANCHISE_CHEF, ROLE_QUALITY_AUDITOR)
    rows = list(db.production_plans.values())
    if actor.is_chef:
        chef = db.chefs.get(actor.user_id)
        assigned = chef["assigned_kiosk_id"] if chef else None
        rows = [p for p in rows if p["kiosk_id"] == assigned]
    elif actor.is_manager:
        rows = [p for p in rows
                if (domain.store_of_kiosk(domain.kiosk_of_plan(p)) or {}).get("id")
                == actor.user_id]
    rows = filters(rows, {
        "kiosk_id": "kiosk_id",
        "production_date": "production_date",
        "status": "status",
        "superseded_plan_id": "superseded_plan_id",
    })
    return paginate(rows)


@bp.post("/production-plans/<plan_id>/release")
def release_plan(plan_id):
    actor = authorize(ROLE_FRANCHISE_CHEF)
    plan = plan_or_404(plan_id)
    _scope_plan(actor, plan)
    with LOCK:
        if plan["status"] != "DRAFT":
            raise ApiError("ERR_PLAN_INVALID_STATE")
        if plan["planned_pack_count"] <= 0:
            raise ApiError("ERR_PLAN_INVALID_STATE")
        kiosk = domain.kiosk_of_plan(plan)
        if kiosk is None or kiosk["operational_state"] != "OPERATING":
            raise ApiError("ERR_KIOSK_INVALID_STATE")
        if kiosk["sanitation_posture"] == "LOCKDOWN":
            raise ApiError("ERR_KIOSK_POSTURE_LOCKDOWN")
        plan["status"] = "RELEASED"
        db.touch(plan)
    return ok(db.public(plan))


@bp.post("/production-plans/<plan_id>/lock")
def lock_plan(plan_id):
    actor = authorize(ROLE_FRANCHISE_CHEF)
    plan = plan_or_404(plan_id)
    _scope_plan(actor, plan)
    with LOCK:
        if plan["status"] != "RELEASED":
            raise ApiError("ERR_PLAN_INVALID_STATE")
        produced = [b for b in domain.batches_of_plan(plan["id"])
                    if b["status"] in ("APPROVED", "VARIANCE_APPROVED", "CONSUMED")]
        if not produced:
            raise ApiError("ERR_PLAN_INVALID_STATE")
        plan["status"] = "LOCKED"
        db.touch(plan)
    return ok(db.public(plan))


@bp.post("/production-plans/<plan_id>/reconcile")
def reconcile_plan(plan_id):
    authorize(ROLE_FRANCHISOR_OPS)
    plan = plan_or_404(plan_id)
    with LOCK:
        if plan["status"] != "LOCKED":
            raise ApiError("ERR_PLAN_INVALID_STATE")
        kiosk = domain.kiosk_of_plan(plan)
        store = domain.store_of_kiosk(kiosk) if kiosk is not None else None
        store_id = store["id"] if store is not None else None
        for feed in db.pos_sales_feeds.values():
            if feed["host_store_id"] != store_id:
                continue
            if feed["business_date"] != plan["production_date"]:
                continue
            if feed["status"] not in ("RECONCILED", "REJECTED"):
                raise ApiError("ERR_PERIOD_FEED_NOT_RECONCILED")
        plan["status"] = "RECONCILED"
        db.touch(plan)
        domain.refresh_plan_actual(plan)
        db.apply_changes(plan, {
            "forecast_variance_pct": calc.forecast_variance_pct(
                plan["planned_pack_count"], plan["actual_pack_count"]),
        })
    return ok(db.public(plan))


@bp.post("/production-plans/<plan_id>/void")
def void_plan_route(plan_id):
    authorize(ROLE_FRANCHISOR_OPS)
    plan = plan_or_404(plan_id)
    payload = body()
    reason = req_str(payload, "void_reason")
    with LOCK:
        if plan["status"] not in ("DRAFT", "RELEASED", "LOCKED"):
            raise ApiError("ERR_PLAN_INVALID_STATE")
        domain.void_plan(plan, reason)
    return ok(db.public(plan))
