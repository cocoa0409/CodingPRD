"""Downtime report endpoints (PRD section 3.5). Append-only."""

from flask import Blueprint, request

import db
import envelope
import helpers
import validators as v
from authz import require_roles
from errors import ApiError, ERR_INVALID_REQUEST

bp = Blueprint("downtime", __name__)

READ_ROLES = ("SiteManager", "BillingOperator")


@bp.post("/api/sites/<site_id>/downtime-reports")
@require_roles("SiteManager")
def create_report(site_id):
    site = helpers.get_site(site_id)
    helpers.ensure_site_open(site)
    data = v.body()
    month = v.month_value(v.req(data, "month"), "month")
    forklift = v.str_value(v.req(data, "forklift_id"), "forklift_id", 1, 60)
    hours = v.number_value(v.req(data, "downtime_hours"), "downtime_hours",
                           ge=0)
    r = helpers.create_rec(db.downtime_reports, {
        "site_id": site_id,
        "month": month,
        "forklift_id": forklift,
        "downtime_hours": hours,
    })
    return envelope.ok(r, 201)


@bp.get("/api/sites/<site_id>/downtime-reports")
@require_roles(*READ_ROLES)
def list_reports(site_id):
    helpers.get_site(site_id)
    items = [r for r in db.downtime_reports.values()
             if r["site_id"] == site_id]
    month = request.args.get("month")
    if month is not None:
        if v.parse_month(month) is None:
            raise ApiError(ERR_INVALID_REQUEST, 400,
                           "month filter must be YYYY-MM")
        items = [r for r in items if r["month"] == month]
    page, meta = helpers.paginate(helpers.sorted_by_created(items))
    return envelope.ok_list(page, meta)
