"""Supply contract endpoints (PRD section 3.2)."""

from flask import Blueprint

import clockops
import db
import envelope
import helpers
import validators as v
from authz import require_roles
from errors import (
    ApiError, ERR_CONTRACT_PERIOD_OVERLAP, ERR_INVALID_DATE_RANGE,
    ERR_INVALID_STATE, ERR_OPEN_INVOICES_EXIST,
)

bp = Blueprint("contracts", __name__)

READ_ROLES = ("SiteManager", "BillingOperator")
SUPPLY_MODES = ("DELIVERED_LIQUID", "ON_SITE_GENERATION", "PIPELINE")


def _get_pair(site_id, cid):
    site = helpers.get_site(site_id)
    c = helpers.get_or_404(db.contracts, cid, "supply contract")
    helpers.ensure_child(c, "site_id", site_id, "supply contract")
    return site, c


@bp.post("/api/sites/<site_id>/supply-contracts")
@require_roles("SiteManager")
def create_contract(site_id):
    site = helpers.get_site(site_id)
    helpers.ensure_site_open(site)
    data = v.body()
    mode = v.enum_value(v.req(data, "supply_mode"), "supply_mode", SUPPLY_MODES)
    start = v.date_value(v.req(data, "start_date"), "start_date")
    end = v.date_value(v.req(data, "end_date"), "end_date")
    price = v.number_value(v.req(data, "base_price_per_kg"),
                           "base_price_per_kg", gt=0)
    sla = v.number_value(v.req(data, "reliability_sla_pct"),
                         "reliability_sla_pct", ge=0, le=100)
    committed = v.number_value(v.req(data, "committed_monthly_kg"),
                               "committed_monthly_kg", gt=0)
    ns, ne = v.parse_date(start), v.parse_date(end)
    if ne < ns:
        raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                       "end_date must be on or after start_date")
    # Half-open [start_date, end_date) overlap against DRAFT/ACTIVE contracts
    # of the same site and same supply_mode; back-to-back is allowed.
    for c in db.contracts.values():
        if (c["site_id"] == site_id and c["supply_mode"] == mode
                and c["status"] in ("DRAFT", "ACTIVE")):
            cs, ce = v.parse_date(c["start_date"]), v.parse_date(c["end_date"])
            if ns < ce and cs < ne:
                raise ApiError(ERR_CONTRACT_PERIOD_OVERLAP, 409,
                               "contract period overlaps an existing "
                               "DRAFT/ACTIVE contract with the same supply_mode")
    c = helpers.create_rec(db.contracts, {
        "site_id": site_id,
        "supply_mode": mode,
        "start_date": start,
        "end_date": end,
        "base_price_per_kg": price,
        "reliability_sla_pct": sla,
        "committed_monthly_kg": committed,
        "status": "DRAFT",
        "terminated_at": None,
    })
    return envelope.ok(c, 201)


@bp.get("/api/sites/<site_id>/supply-contracts")
@require_roles(*READ_ROLES)
def list_contracts(site_id):
    helpers.get_site(site_id)
    items = [c for c in db.contracts.values() if c["site_id"] == site_id]
    page, meta = helpers.paginate(helpers.sorted_by_created(items))
    return envelope.ok_list(page, meta)


@bp.get("/api/supply-contracts/<cid>")
@require_roles(*READ_ROLES)
def get_contract(cid):
    return envelope.ok(helpers.get_or_404(db.contracts, cid,
                                          "supply contract"), 200)


@bp.get("/api/supply-contracts/<cid>/fueling-events")
@require_roles(*READ_ROLES)
def list_contract_fueling_events(cid):
    helpers.get_or_404(db.contracts, cid, "supply contract")
    items = [e for e in db.fueling_events.values()
             if e["supply_contract_id"] == cid]
    page, meta = helpers.paginate(helpers.sorted_by_created(items))
    return envelope.ok_list(page, meta)


@bp.get("/api/supply-contracts/<cid>/invoices")
@require_roles(*READ_ROLES)
def list_contract_invoices(cid):
    helpers.get_or_404(db.contracts, cid, "supply contract")
    items = [i for i in db.invoices.values()
             if i["supply_contract_id"] == cid]
    page, meta = helpers.paginate(helpers.sorted_by_created(items))
    return envelope.ok_list(page, meta)


@bp.post("/api/sites/<site_id>/supply-contracts/<cid>/activate")
@require_roles("SiteManager")
def activate_contract(site_id, cid):
    site, c = _get_pair(site_id, cid)
    if c["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "contract must be DRAFT to activate")
    helpers.ensure_site_open(site)
    c["status"] = "ACTIVE"
    helpers.touch(c)
    if site["status"] == "SUSPENDED":
        site["status"] = "ACTIVE"
        helpers.touch(site)
    return envelope.ok(c, 200)


@bp.post("/api/sites/<site_id>/supply-contracts/<cid>/terminate")
@require_roles("SiteManager")
def terminate_contract(site_id, cid):
    site, c = _get_pair(site_id, cid)
    if c["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "contract must be ACTIVE to terminate")
    helpers.ensure_site_open(site)
    for inv in db.invoices.values():
        if (inv["supply_contract_id"] == cid
                and inv["status"] in ("DRAFT", "ISSUED", "DISPUTED")):
            raise ApiError(ERR_OPEN_INVOICES_EXIST, 422,
                           "open invoices block contract termination")
    c["status"] = "TERMINATED"
    c["terminated_at"] = db.clock_stamp()
    helpers.touch(c)
    clockops.maybe_suspend_site(site_id)
    return envelope.ok(c, 200)
