"""Conversion plan endpoints (PRD section 3.4)."""

from flask import Blueprint

import db
import envelope
import helpers
import validators as v
from authz import require_roles
from errors import (
    ApiError, ERR_ASSESSMENT_NOT_APPROVED, ERR_INVALID_DATE_RANGE,
    ERR_INVALID_STATE, ERR_STALE_VERSION,
)

bp = Blueprint("plans", __name__)

READ_ROLES = ("SiteManager", "ConversionTechnician")
TRANSITION_MODES = ("PARALLEL", "CUTOVER")


def _get_pair(site_id, pid):
    site = helpers.get_site(site_id)
    p = helpers.get_or_404(db.plans, pid, "conversion plan")
    helpers.ensure_child(p, "site_id", site_id, "conversion plan")
    return site, p


@bp.post("/api/sites/<site_id>/conversion-plans")
@require_roles("SiteManager")
def create_plan(site_id):
    site = helpers.get_site(site_id)
    helpers.ensure_site_open(site)
    data = v.body()
    name = v.str_value(v.req(data, "name"), "name", 1, 80)
    target = v.int_value(v.req(data, "target_forklift_count"),
                         "target_forklift_count", ge=1)
    mode = v.enum_value(v.req(data, "transition_mode"), "transition_mode",
                        TRANSITION_MODES)
    start = v.date_value(v.req(data, "start_date"), "start_date")
    end = v.date_value(v.req(data, "end_date"), "end_date")
    baseline = v.number_value(v.req(data, "baseline_productivity_units_per_hour"),
                              "baseline_productivity_units_per_hour", gt=0)
    gain = v.number_value(v.req(data, "expected_productivity_gain_pct"),
                          "expected_productivity_gain_pct", ge=0)
    if v.parse_date(end) <= v.parse_date(start):
        raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                       "end_date must be after start_date")
    p = helpers.create_rec(db.plans, {
        "site_id": site_id,
        "name": name,
        "target_forklift_count": target,
        "transition_mode": mode,
        "start_date": start,
        "end_date": end,
        "status": "DRAFT",
        "baseline_productivity_units_per_hour": baseline,
        "expected_productivity_gain_pct": gain,
    })
    return envelope.ok(p, 201)


@bp.get("/api/sites/<site_id>/conversion-plans")
@require_roles(*READ_ROLES)
def list_plans(site_id):
    helpers.get_site(site_id)
    items = [p for p in db.plans.values() if p["site_id"] == site_id]
    page, meta = helpers.paginate(helpers.sorted_by_created(items))
    return envelope.ok_list(page, meta)


@bp.get("/api/conversion-plans/<pid>")
@require_roles(*READ_ROLES)
def get_plan(pid):
    return envelope.ok(helpers.get_or_404(db.plans, pid,
                                          "conversion plan"), 200)


@bp.post("/api/sites/<site_id>/conversion-plans/<pid>/schedule")
@require_roles("SiteManager")
def schedule_plan(site_id, pid):
    site, plan = _get_pair(site_id, pid)
    if plan["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "plan must be DRAFT to schedule")
    helpers.ensure_site_open(site)
    if site["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "site must be ACTIVE to schedule a plan")
    data = v.body()
    expected = v.int_value(v.req(data, "expected_plan_version"),
                           "expected_plan_version")
    approved = [a for a in db.assessments.values()
                if a["site_id"] == site_id and a["status"] == "APPROVED"]
    if not approved:
        raise ApiError(ERR_ASSESSMENT_NOT_APPROVED, 422,
                       "an APPROVED assessment is required to schedule a plan")
    latest = max(approved, key=lambda a: a["created_at"])
    if plan["target_forklift_count"] > latest["forklift_count"]:
        raise ApiError(ERR_ASSESSMENT_NOT_APPROVED, 422,
                       "target_forklift_count exceeds the approved "
                       "assessment forklift_count")
    if expected != plan["version"]:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "expected_plan_version does not match the plan version")
    plan["status"] = "SCHEDULED"
    helpers.touch(plan)
    return envelope.ok(plan, 200)


@bp.post("/api/sites/<site_id>/conversion-plans/<pid>/revert")
@require_roles("SiteManager")
def revert_plan(site_id, pid):
    site, plan = _get_pair(site_id, pid)
    if plan["status"] != "SCHEDULED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "plan must be SCHEDULED to revert")
    helpers.ensure_site_open(site)
    if any(e["conversion_plan_id"] == pid and e["status"] == "COMPLETED"
           for e in db.events.values()):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "cannot revert a plan with a COMPLETED conversion event")
    plan["status"] = "DRAFT"
    helpers.touch(plan)
    return envelope.ok(plan, 200)


@bp.post("/api/sites/<site_id>/conversion-plans/<pid>/cancel")
@require_roles("SiteManager")
def cancel_plan(site_id, pid):
    site, plan = _get_pair(site_id, pid)
    if plan["status"] != "IN_PROGRESS":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "plan must be IN_PROGRESS to cancel")
    helpers.ensure_site_open(site)
    plan["status"] = "CANCELLED"
    helpers.touch(plan)
    for e in db.events.values():
        if (e["conversion_plan_id"] == pid
                and e["status"] in ("SCHEDULED", "IN_PROGRESS")):
            e["status"] = "CANCELLED"
            helpers.touch(e)
    return envelope.ok(plan, 200)
