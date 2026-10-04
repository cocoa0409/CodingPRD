"""Site endpoints (PRD section 3.1)."""

from flask import Blueprint, request

import calc
import db
import envelope
import helpers
import validators as v
from authz import require_roles
from errors import (
    ApiError, ERR_DUPLICATE_CODE, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
)

bp = Blueprint("sites", __name__)

READ_ROLES = ("SiteManager", "SafetyOfficer", "ComplianceOfficer",
              "BillingOperator", "PlatformAdmin")
SITE_STATUSES = ("ACTIVE", "SUSPENDED", "CLOSED")


@bp.post("/api/sites")
@require_roles("SiteManager")
def create_site():
    data = v.body()
    code = v.str_value(v.req(data, "code"), "code", 1, 40)
    name = v.str_value(v.req(data, "name"), "name", 1, 120)
    address = v.str_value(v.req(data, "address"), "address", 1, 200)
    rate = v.number_value(v.req(data, "baseline_labor_rate_per_hour"),
                          "baseline_labor_rate_per_hour", ge=0.01)
    for s in db.sites.values():
        if s["code"] == code:
            raise ApiError(ERR_DUPLICATE_CODE, 409, "site code already exists")
    site = helpers.create_rec(db.sites, {
        "code": code,
        "name": name,
        "address": address,
        "status": "ACTIVE",
        "baseline_labor_rate_per_hour": rate,
        "actual_productivity_units_per_hour": None,
    })
    return envelope.ok(site, 201)


@bp.get("/api/sites")
@require_roles(*READ_ROLES)
def list_sites():
    items = list(db.sites.values())
    status = request.args.get("status")
    if status is not None:
        if status not in SITE_STATUSES:
            raise ApiError(ERR_INVALID_REQUEST, 400, "invalid status filter")
        items = [s for s in items if s["status"] == status]
    page, meta = helpers.paginate(helpers.sorted_by_created(items))
    return envelope.ok_list(page, meta)


@bp.get("/api/sites/<site_id>")
@require_roles(*READ_ROLES)
def get_site(site_id):
    return envelope.ok(helpers.get_site(site_id), 200)


@bp.post("/api/sites/<site_id>/close")
@require_roles("SiteManager")
def close_site(site_id):
    site = helpers.get_site(site_id)
    if site["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "only an ACTIVE site can be closed")
    site["status"] = "CLOSED"
    helpers.touch(site)
    return envelope.ok(site, 200)


@bp.post("/api/sites/<site_id>/record-productivity")
@require_roles("SiteManager")
def record_productivity(site_id):
    site = helpers.get_site(site_id)
    helpers.ensure_site_open(site)
    data = v.body()
    mode = v.enum_value(v.req(data, "measurement_mode"), "measurement_mode",
                        ("TELEMATICS", "SELF_REPORTED"))
    reported = v.number_value(v.req(data, "reported_units_per_hour"),
                              "reported_units_per_hour", ge=0)
    site["actual_productivity_units_per_hour"] = calc.recorded_productivity(
        mode, reported)
    helpers.touch(site)
    return envelope.ok(site, 200)
