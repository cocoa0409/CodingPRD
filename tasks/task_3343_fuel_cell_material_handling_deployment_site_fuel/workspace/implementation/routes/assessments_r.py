"""Assessment endpoints (PRD section 3.1)."""

import json

from flask import Blueprint

import calc
import db
import envelope
import helpers
import validators as v
from authz import require_roles
from errors import ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE

bp = Blueprint("assessments", __name__)

READ_ROLES = ("SiteManager", "SafetyOfficer")


def _findings_value(raw):
    s = v.str_value(raw, "safety_findings_json")
    try:
        parsed = json.loads(s)
    except (ValueError, TypeError):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "safety_findings_json must parse as a JSON object")
    if not isinstance(parsed, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       "safety_findings_json must parse as a JSON object")
    return s


def _get_pair(site_id, aid):
    site = helpers.get_site(site_id)
    a = helpers.get_or_404(db.assessments, aid, "assessment")
    helpers.ensure_child(a, "site_id", site_id, "assessment")
    return site, a


def _recompute(a):
    a["daily_kg_estimate"] = calc.daily_kg_estimate(
        a["forklift_count"], a["duty_cycle_hours_per_day"], a["peak_shift_hours"])


@bp.post("/api/sites/<site_id>/assessments")
@require_roles("SiteManager")
def create_assessment(site_id):
    site = helpers.get_site(site_id)
    helpers.ensure_site_open(site)
    data = v.body()
    fc = v.int_value(v.req(data, "forklift_count"), "forklift_count", ge=1)
    duty = v.number_value(v.req(data, "duty_cycle_hours_per_day"),
                          "duty_cycle_hours_per_day", gt=0)
    peak = v.int_value(v.req(data, "peak_shift_hours"), "peak_shift_hours",
                       ge=1, le=24)
    findings = _findings_value(v.req(data, "safety_findings_json"))
    a = helpers.create_rec(db.assessments, {
        "site_id": site_id,
        "forklift_count": fc,
        "duty_cycle_hours_per_day": duty,
        "peak_shift_hours": peak,
        "daily_kg_estimate": calc.daily_kg_estimate(fc, duty, peak),
        "safety_findings_json": findings,
        "status": "DRAFT",
    })
    return envelope.ok(a, 201)


@bp.get("/api/sites/<site_id>/assessments")
@require_roles(*READ_ROLES)
def list_assessments(site_id):
    helpers.get_site(site_id)
    items = [a for a in db.assessments.values() if a["site_id"] == site_id]
    page, meta = helpers.paginate(helpers.sorted_by_created(items))
    return envelope.ok_list(page, meta)


@bp.get("/api/assessments/<aid>")
@require_roles(*READ_ROLES)
def get_assessment(aid):
    return envelope.ok(helpers.get_or_404(db.assessments, aid, "assessment"), 200)


@bp.put("/api/assessments/<aid>")
@require_roles("SiteManager")
def update_assessment(aid):
    a = helpers.get_or_404(db.assessments, aid, "assessment")
    if a["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError(ERR_INVALID_STATE, 409,
                       "assessment can only be updated while DRAFT or REJECTED")
    site = helpers.get_site(a["site_id"])
    helpers.ensure_site_open(site)
    data = v.body()
    if "forklift_count" in data:
        a["forklift_count"] = v.int_value(data["forklift_count"],
                                          "forklift_count", ge=1)
    if "duty_cycle_hours_per_day" in data:
        a["duty_cycle_hours_per_day"] = v.number_value(
            data["duty_cycle_hours_per_day"], "duty_cycle_hours_per_day", gt=0)
    if "peak_shift_hours" in data:
        a["peak_shift_hours"] = v.int_value(data["peak_shift_hours"],
                                            "peak_shift_hours", ge=1, le=24)
    if "safety_findings_json" in data:
        a["safety_findings_json"] = _findings_value(data["safety_findings_json"])
    _recompute(a)
    helpers.touch(a)
    return envelope.ok(a, 200)


@bp.post("/api/sites/<site_id>/assessments/<aid>/submit")
@require_roles("SiteManager")
def submit_assessment(site_id, aid):
    site, a = _get_pair(site_id, aid)
    if a["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "assessment must be DRAFT to submit")
    helpers.ensure_site_open(site)
    if site["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "site must be ACTIVE to submit an assessment")
    _recompute(a)
    a["status"] = "SUBMITTED"
    helpers.touch(a)
    return envelope.ok(a, 200)


@bp.post("/api/sites/<site_id>/assessments/<aid>/approve")
@require_roles("SafetyOfficer")
def approve_assessment(site_id, aid):
    site, a = _get_pair(site_id, aid)
    if a["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "assessment must be SUBMITTED to approve")
    helpers.ensure_site_open(site)
    if site["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "site must be ACTIVE to approve an assessment")
    a["status"] = "APPROVED"
    helpers.touch(a)
    return envelope.ok(a, 200)


@bp.post("/api/sites/<site_id>/assessments/<aid>/reject")
@require_roles("SafetyOfficer")
def reject_assessment(site_id, aid):
    site, a = _get_pair(site_id, aid)
    if a["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "assessment must be SUBMITTED to reject")
    helpers.ensure_site_open(site)
    a["status"] = "REJECTED"
    helpers.touch(a)
    return envelope.ok(a, 200)


@bp.post("/api/sites/<site_id>/assessments/<aid>/revise")
@require_roles("SiteManager")
def revise_assessment(site_id, aid):
    site, a = _get_pair(site_id, aid)
    if a["status"] != "REJECTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "assessment must be REJECTED to revise")
    helpers.ensure_site_open(site)
    a["status"] = "DRAFT"
    helpers.touch(a)
    return envelope.ok(a, 200)
