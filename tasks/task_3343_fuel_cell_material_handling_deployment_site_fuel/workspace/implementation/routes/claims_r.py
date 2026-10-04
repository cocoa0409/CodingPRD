"""Incentive claim endpoints (PRD section 3.7)."""

from flask import Blueprint

import calc
import db
import envelope
import helpers
import validators as v
from authz import require_roles
from errors import ApiError, ERR_INVALID_STATE, ERR_PRODUCTIVITY_GATE_NOT_MET

bp = Blueprint("claims", __name__)

READ_ROLES = ("SiteManager", "ComplianceOfficer")
INCENTIVE_TYPES = ("FEDERAL_ITC", "STATE_REBATE", "UTILITY_GRANT")


def _get_pair(site_id, cid):
    site = helpers.get_site(site_id)
    c = helpers.get_or_404(db.claims, cid, "incentive claim")
    helpers.ensure_child(c, "site_id", site_id, "incentive claim")
    return site, c


@bp.post("/api/sites/<site_id>/incentive-claims")
@require_roles("SiteManager")
def create_claim(site_id):
    site = helpers.get_site(site_id)
    helpers.ensure_site_open(site)
    data = v.body()
    itype = v.enum_value(v.req(data, "incentive_type"), "incentive_type",
                         INCENTIVE_TYPES)
    claimed = v.int_value(v.req(data, "claimed_amount_cents"),
                          "claimed_amount_cents", ge=0)
    qdate = v.date_value(v.req(data, "qualification_date"),
                         "qualification_date")
    c = helpers.create_rec(db.claims, {
        "site_id": site_id,
        "incentive_type": itype,
        "claimed_amount_cents": claimed,
        "qualification_date": qdate,
        "approved_amount_cents": None,
        "status": "DRAFT",
    })
    return envelope.ok(c, 201)


@bp.get("/api/sites/<site_id>/incentive-claims")
@require_roles(*READ_ROLES)
def list_claims(site_id):
    helpers.get_site(site_id)
    items = [c for c in db.claims.values() if c["site_id"] == site_id]
    page, meta = helpers.paginate(helpers.sorted_by_created(items))
    return envelope.ok_list(page, meta)


@bp.get("/api/incentive-claims/<cid>")
@require_roles(*READ_ROLES)
def get_claim(cid):
    return envelope.ok(helpers.get_or_404(db.claims, cid,
                                          "incentive claim"), 200)


@bp.post("/api/sites/<site_id>/incentive-claims/<cid>/submit")
@require_roles("SiteManager")
def submit_claim(site_id, cid):
    site, c = _get_pair(site_id, cid)
    if c["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "claim must be DRAFT to submit")
    helpers.ensure_site_open(site)
    if site["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "site must be ACTIVE to submit a claim")
    c["status"] = "SUBMITTED"
    helpers.touch(c)
    return envelope.ok(c, 200)


@bp.post("/api/sites/<site_id>/incentive-claims/<cid>/approve")
@require_roles("ComplianceOfficer")
def approve_claim(site_id, cid):
    site, c = _get_pair(site_id, cid)
    if c["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "claim must be SUBMITTED to approve")
    helpers.ensure_site_open(site)
    if c["incentive_type"] == "FEDERAL_ITC":
        plan = calc.governing_completed_plan(site_id)
        if plan is None or not calc.productivity_gate_passes(site, plan):
            raise ApiError(ERR_PRODUCTIVITY_GATE_NOT_MET, 422,
                           "no COMPLETED conversion plan or recorded "
                           "productivity is below the expected threshold")
        c["approved_amount_cents"] = calc.incentive_amount(
            plan, c["claimed_amount_cents"])
    else:
        c["approved_amount_cents"] = c["claimed_amount_cents"]
    c["status"] = "APPROVED"
    helpers.touch(c)
    return envelope.ok(c, 200)


@bp.post("/api/sites/<site_id>/incentive-claims/<cid>/reject")
@require_roles("ComplianceOfficer")
def reject_claim(site_id, cid):
    site, c = _get_pair(site_id, cid)
    if c["status"] != "SUBMITTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "claim must be SUBMITTED to reject")
    helpers.ensure_site_open(site)
    c["status"] = "REJECTED"
    helpers.touch(c)
    return envelope.ok(c, 200)
