"""Service agreement endpoints (PRD section 3.5)."""

from flask import Blueprint

import db
import envelope
import helpers
import validators as v
from authz import require_roles
from errors import ApiError, ERR_INVALID_DATE_RANGE, ERR_INVALID_STATE

bp = Blueprint("agreements", __name__)

READ_ROLES = ("SiteManager", "BillingOperator")


def _get_pair(site_id, aid):
    site = helpers.get_site(site_id)
    a = helpers.get_or_404(db.agreements, aid, "service agreement")
    helpers.ensure_child(a, "site_id", site_id, "service agreement")
    return site, a


@bp.post("/api/sites/<site_id>/service-agreements")
@require_roles("SiteManager")
def create_agreement(site_id):
    site = helpers.get_site(site_id)
    helpers.ensure_site_open(site)
    data = v.body()
    start = v.date_value(v.req(data, "coverage_start"), "coverage_start")
    end = v.date_value(v.req(data, "coverage_end"), "coverage_end")
    guarantee = v.number_value(v.req(data, "availability_guarantee_pct"),
                               "availability_guarantee_pct", gt=0, le=100)
    fee = v.int_value(v.req(data, "monthly_fee_cents"), "monthly_fee_cents",
                      ge=0)
    stack = False
    if "stack_replacement_included" in data and data["stack_replacement_included"] is not None:
        stack = v.bool_value(data["stack_replacement_included"],
                             "stack_replacement_included")
    if v.parse_date(end) <= v.parse_date(start):
        raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                       "coverage_end must be after coverage_start")
    a = helpers.create_rec(db.agreements, {
        "site_id": site_id,
        "coverage_start": start,
        "coverage_end": end,
        "stack_replacement_included": stack,
        "availability_guarantee_pct": guarantee,
        "monthly_fee_cents": fee,
        "status": "DRAFT",
    })
    return envelope.ok(a, 201)


@bp.get("/api/sites/<site_id>/service-agreements")
@require_roles(*READ_ROLES)
def list_agreements(site_id):
    helpers.get_site(site_id)
    items = [a for a in db.agreements.values() if a["site_id"] == site_id]
    page, meta = helpers.paginate(helpers.sorted_by_created(items))
    return envelope.ok_list(page, meta)


@bp.get("/api/service-agreements/<aid>")
@require_roles(*READ_ROLES)
def get_agreement(aid):
    return envelope.ok(helpers.get_or_404(db.agreements, aid,
                                          "service agreement"), 200)


@bp.post("/api/sites/<site_id>/service-agreements/<aid>/activate")
@require_roles("SiteManager")
def activate_agreement(site_id, aid):
    site, a = _get_pair(site_id, aid)
    if a["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "agreement must be DRAFT to activate")
    helpers.ensure_site_open(site)
    if site["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "site must be ACTIVE to activate an agreement")
    a["status"] = "ACTIVE"
    helpers.touch(a)
    return envelope.ok(a, 200)


@bp.post("/api/sites/<site_id>/service-agreements/<aid>/terminate")
@require_roles("SiteManager")
def terminate_agreement(site_id, aid):
    site, a = _get_pair(site_id, aid)
    if a["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "agreement must be ACTIVE to terminate")
    helpers.ensure_site_open(site)
    a["status"] = "TERMINATED"
    helpers.touch(a)
    return envelope.ok(a, 200)
