import re

from flask import Blueprint, request

import db
from errors import (
    err_no_active_policy, err_not_found, err_plan_not_later,
    err_policy_already_active, err_validation,
)
from helpers import (
    active_plan, body, format_dt, get_agency_or_404, get_scoped, new_resource,
    paginate, parse_dt, reject_unknown, require_enum, require_int, require_str,
    success_obj, touch, write_audit,
)
from middleware import authenticate, require_roles
import services

bp = Blueprint("misc", __name__)

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    actor = authenticate()
    require_roles(actor, "AgencyAdmin")
    data = body()
    reject_unknown(data, {"to_iso8601"})
    raw = require_str(data, "to_iso8601")
    dt = parse_dt(raw)
    if dt is None:
        raise err_validation("to_iso8601 must be an ISO 8601 timestamp")
    db.set_clock(format_dt(dt))
    return success_obj({"current_utc": db.get_clock()})


# ---------------------------------------------------------------- agencies

@bp.route("/agencies", methods=["POST"])
def create_agency():
    actor = authenticate()
    require_roles(actor, "AgencyAdmin")
    data = body()
    reject_unknown(data, {"name", "timezone"})
    name = require_str(data, "name")
    timezone = data.get("timezone", "UTC")
    if timezone is not None and not isinstance(timezone, str):
        raise err_validation("timezone must be a string")
    agency = new_resource({
        "name": name,
        "timezone": timezone or "UTC",
        "storage_used_bytes": 0,
        "storage_posture": "OK",
    })
    db.collection("agencies")[agency["id"]] = agency
    return success_obj(agency, 201)


@bp.route("/agencies/<agency_id>", methods=["GET"])
def get_agency(agency_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "DeviceCoordinator", "Officer",
                  "Supervisor", "RedactionTechnician", "RecordsOfficer")
    agency = get_agency_or_404(agency_id)
    return success_obj(agency)


# ---------------------------------------------------------------- policies

@bp.route("/agencies/<agency_id>/policies", methods=["POST"])
def create_policy(agency_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin")
    agency = get_agency_or_404(agency_id)
    data = body()
    reject_unknown(data, {"recording_triggers", "tagging_required",
                          "supervisor_review_rate_pct", "default_share_expiry_days"})
    triggers = data.get("recording_triggers")
    if not isinstance(triggers, list) or len(triggers) < 1:
        raise err_validation("recording_triggers must be a non-empty list")
    for t in triggers:
        if t not in services.TRIGGERS:
            raise err_validation("unknown recording trigger: %s" % t)
    tagging = data.get("tagging_required")
    if not isinstance(tagging, bool):
        raise err_validation("tagging_required must be a boolean")
    rate = require_int(data, "supervisor_review_rate_pct")
    if rate < 0 or rate > 100:
        raise err_validation("supervisor_review_rate_pct must be 0..100")
    expiry = require_int(data, "default_share_expiry_days")
    if expiry < 1 or expiry > 90:
        raise err_validation("default_share_expiry_days must be 1..90")
    policy = new_resource({
        "agency_id": agency["id"],
        "recording_triggers": list(triggers),
        "tagging_required": tagging,
        "supervisor_review_rate_pct": rate,
        "default_share_expiry_days": expiry,
        "status": "DRAFT",
    })
    db.collection("policies")[policy["id"]] = policy
    return success_obj(policy, 201)


@bp.route("/agencies/<agency_id>/policies/<policy_id>/activate", methods=["POST"])
def activate_policy(agency_id, policy_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin")
    agency = get_agency_or_404(agency_id)
    policy = get_scoped("policies", agency, policy_id, "Policy")
    if policy["status"] != "DRAFT":
        from errors import err_invalid_state
        raise err_invalid_state("Only a DRAFT policy can be activated")
    for p in db.collection("policies").values():
        if p["agency_id"] == agency["id"] and p["status"] == "ACTIVE":
            raise err_policy_already_active()
    policy["status"] = "ACTIVE"
    touch(policy)
    write_audit(agency["id"], actor, "POLICY_ACTIVATED", "AgencyPolicy",
                policy["id"], "status DRAFT -> ACTIVE")
    return success_obj(policy)


@bp.route("/agencies/<agency_id>/policies/<policy_id>/supersede", methods=["POST"])
def supersede_policy(agency_id, policy_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin")
    agency = get_agency_or_404(agency_id)
    policy = get_scoped("policies", agency, policy_id, "Policy")
    if policy["status"] != "ACTIVE":
        from errors import err_invalid_state
        raise err_invalid_state("Only the ACTIVE policy can be superseded")
    policy["status"] = "SUPERSEDED"
    touch(policy)
    write_audit(agency["id"], actor, "POLICY_SUPERSEDED", "AgencyPolicy",
                policy["id"], "status ACTIVE -> SUPERSEDED")
    return success_obj(policy)


@bp.route("/agencies/policies", methods=["GET"])
def list_policies():
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "Supervisor", "RecordsOfficer")
    items = list(db.collection("policies").values())
    agency_id = request.args.get("agency_id")
    if agency_id:
        items = [p for p in items if p["agency_id"] == agency_id]
    return paginate(items)


@bp.route("/agencies/policies/<policy_id>", methods=["GET"])
def get_policy(policy_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "Supervisor", "RecordsOfficer")
    policy = db.collection("policies").get(policy_id)
    if policy is None:
        raise err_not_found("Policy not found")
    return success_obj(policy)


# ---------------------------------------------------------------- budget plans

@bp.route("/agencies/<agency_id>/storage-budget-plans", methods=["POST"])
def create_plan(agency_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin")
    agency = get_agency_or_404(agency_id)
    data = body()
    reject_unknown(data, {"fiscal_year_start_month", "monthly_budget_cents",
                          "cost_per_gb_month_cents", "alert_threshold_pct",
                          "effective_from_month"})
    fysm = require_int(data, "fiscal_year_start_month")
    if fysm < 1 or fysm > 12:
        raise err_validation("fiscal_year_start_month must be 1..12")
    budget = require_int(data, "monthly_budget_cents")
    rate = require_int(data, "cost_per_gb_month_cents")
    threshold = require_int(data, "alert_threshold_pct")
    if threshold < 1 or threshold > 99:
        raise err_validation("alert_threshold_pct must be 1..99")
    efm = require_str(data, "effective_from_month")
    prior = active_plan(agency["id"])
    if prior is not None and efm <= prior["effective_from_month"]:
        raise err_plan_not_later()
    if not MONTH_RE.match(efm):
        raise err_validation("effective_from_month must be YYYY-MM")

    plan = new_resource({
        "agency_id": agency["id"],
        "fiscal_year_start_month": fysm,
        "monthly_budget_cents": budget,
        "cost_per_gb_month_cents": rate,
        "alert_threshold_pct": threshold,
        "effective_from_month": efm,
        "status": "ACTIVE",
    })
    db.collection("plans")[plan["id"]] = plan
    if prior is not None:
        prior["status"] = "SUPERSEDED"
        touch(prior)
        write_audit(agency["id"], actor, "BUDGET_PLAN_SUPERSEDED",
                    "StorageBudgetPlan", prior["id"],
                    "superseded by plan %s" % plan["id"])
    services.touch_agency(agency)
    return success_obj(plan, 201)


@bp.route("/agencies/budget-plans", methods=["GET"])
def list_plans():
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "RecordsOfficer")
    items = list(db.collection("plans").values())
    agency_id = request.args.get("agency_id")
    if agency_id:
        items = [p for p in items if p["agency_id"] == agency_id]
    return paginate(items)


@bp.route("/agencies/budget-plans/<plan_id>", methods=["GET"])
def get_plan(plan_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "RecordsOfficer")
    plan = db.collection("plans").get(plan_id)
    if plan is None:
        raise err_not_found("Budget plan not found")
    return success_obj(plan)


@bp.route("/agencies/<agency_id>/storage/budget-projection", methods=["GET"])
def budget_projection(agency_id):
    actor = authenticate()
    require_roles(actor, "AgencyAdmin", "RecordsOfficer")
    agency = get_agency_or_404(agency_id)
    plan = active_plan(agency["id"])
    if plan is None:
        raise err_not_found("No ACTIVE storage budget plan")

    months_raw = request.args.get("months")
    growth_raw = request.args.get("plan_growth_bps")
    months = 1
    growth_bps = 0
    if months_raw is not None:
        try:
            months = int(months_raw)
        except (TypeError, ValueError):
            raise err_validation("months must be an integer")
        if months < 1 or months > 60:
            raise err_validation("months must be 1..60")
    if growth_raw is not None:
        try:
            growth_bps = int(growth_raw)
        except (TypeError, ValueError):
            raise err_validation("plan_growth_bps must be an integer")

    from helpers import iso_now
    now_dt = parse_dt(iso_now())

    used = agency["storage_used_bytes"]
    full_month = services.storage_full_month_cost_cents(used, plan)
    accrued = services.storage_accrued_cost_cents(used, plan, now_dt)
    services.recompute_posture(agency)

    growth = 1 + growth_bps / 10000.0
    month_entries = []
    total = 0
    first_over = None
    for m in range(months):
        projected_bytes = used * (growth ** m)
        cost = services.math.ceil((projected_bytes / services.GIB) * plan["cost_per_gb_month_cents"])
        over = cost > plan["monthly_budget_cents"]
        if over and first_over is None:
            first_over = m
        month_entries.append({
            "month_index": m,
            "projected_cost_cents": cost,
            "over_budget": over,
        })
        total += cost

    result = {
        "current_month_accrued_cost_cents": accrued,
        "projection_month_cost_cents": full_month,
        "posture": agency["storage_posture"],
        "months": month_entries,
        "total_projected_cost_cents": total,
        "first_over_budget_month_index": first_over,
    }
    return success_obj(result)
