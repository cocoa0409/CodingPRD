"""Fueling event endpoints (PRD section 3.6)."""

from flask import Blueprint

import db
import envelope
import helpers
import validators as v
from authz import require_roles
from errors import ApiError, ERR_NO_ACTIVE_CONTRACT, ERR_STATION_NOT_COMMISSIONED

bp = Blueprint("fueling", __name__)

READ_ROLES = ("SiteManager", "BillingOperator")


@bp.post("/api/stations/<sid>/fueling-events")
@require_roles("SiteManager")
def create_fueling_event(sid):
    st = helpers.get_or_404(db.stations, sid, "station")
    site = helpers.get_site(st["site_id"])
    helpers.ensure_site_open(site)
    data = v.body()
    forklift = v.str_value(v.req(data, "forklift_id"), "forklift_id", 1, 60)
    occurred = v.datetime_value(v.req(data, "occurred_at"), "occurred_at")
    kg = v.number_value(v.req(data, "kg_dispensed"), "kg_dispensed", gt=0)
    contract_id = v.str_value(v.req(data, "supply_contract_id"),
                              "supply_contract_id")
    odt = v.parse_datetime(occurred)
    if (st["construction_status"] != "COMMISSIONED"
            or odt < v.parse_datetime(st["commissioned_at"])):
        raise ApiError(ERR_STATION_NOT_COMMISSIONED, 422,
                       "station is not COMMISSIONED or occurred_at precedes "
                       "commissioned_at")
    c = db.contracts.get(contract_id)
    if (c is None or c["status"] != "ACTIVE"
            or c["site_id"] != st["site_id"]):
        raise ApiError(ERR_NO_ACTIVE_CONTRACT, 422,
                       "supply contract is not ACTIVE for this site")
    if not (v.parse_date(c["start_date"]) <= odt.date()
            <= v.parse_date(c["end_date"])):
        raise ApiError(ERR_NO_ACTIVE_CONTRACT, 422,
                       "supply contract does not cover occurred_at")
    ev = helpers.create_rec(db.fueling_events, {
        "station_id": sid,
        "forklift_id": forklift,
        "occurred_at": occurred,
        "kg_dispensed": kg,
        "supply_contract_id": contract_id,
    })
    return envelope.ok(ev, 201)


@bp.get("/api/stations/<sid>/fueling-events")
@require_roles(*READ_ROLES)
def list_station_events(sid):
    helpers.get_or_404(db.stations, sid, "station")
    items = [e for e in db.fueling_events.values() if e["station_id"] == sid]
    page, meta = helpers.paginate(helpers.sorted_by_created(items))
    return envelope.ok_list(page, meta)


@bp.get("/api/fueling-events/<eid>")
@require_roles(*READ_ROLES)
def get_fueling_event(eid):
    return envelope.ok(helpers.get_or_404(db.fueling_events, eid,
                                          "fueling event"), 200)


@bp.get("/api/fueling-events/<eid>/line-items")
@require_roles(*READ_ROLES)
def list_event_line_items(eid):
    helpers.get_or_404(db.fueling_events, eid, "fueling event")
    items = [li for li in db.line_items.values()
             if li["fueling_event_id"] == eid]
    page, meta = helpers.paginate(helpers.sorted_by_created(items))
    return envelope.ok_list(page, meta)
