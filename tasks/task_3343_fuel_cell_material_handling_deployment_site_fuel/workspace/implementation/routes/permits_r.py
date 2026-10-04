"""Permit endpoints (PRD section 3.3)."""

from flask import Blueprint

import db
import envelope
import helpers
import validators as v
from authz import require_roles
from errors import ApiError, ERR_INVALID_DATE_RANGE, ERR_INVALID_STATE

bp = Blueprint("permits", __name__)

READ_ROLES = ("SiteManager", "ComplianceOfficer")
PERMIT_TYPES = ("CONSTRUCTION", "FIRE", "DISPENSING_INDOOR")


def _get_pair(sid, pid):
    st = helpers.get_or_404(db.stations, sid, "station")
    p = helpers.get_or_404(db.permits, pid, "permit")
    helpers.ensure_child(p, "station_id", sid, "permit")
    return st, p


@bp.post("/api/stations/<sid>/permits")
@require_roles("SiteManager")
def create_permit(sid):
    st = helpers.get_or_404(db.stations, sid, "station")
    site = helpers.get_site(st["site_id"])
    helpers.ensure_site_open(site)
    data = v.body()
    ptype = v.enum_value(v.req(data, "permit_type"), "permit_type",
                         PERMIT_TYPES)
    issued = v.date_value(v.req(data, "issued_date"), "issued_date")
    expiry = v.date_value(v.req(data, "expiry_date"), "expiry_date")
    if v.parse_date(expiry) <= v.parse_date(issued):
        raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                       "expiry_date must be after issued_date")
    p = helpers.create_rec(db.permits, {
        "station_id": sid,
        "permit_type": ptype,
        "issued_date": issued,
        "expiry_date": expiry,
        "status": "PENDING",
    })
    return envelope.ok(p, 201)


@bp.get("/api/stations/<sid>/permits")
@require_roles(*READ_ROLES)
def list_permits(sid):
    helpers.get_or_404(db.stations, sid, "station")
    items = [p for p in db.permits.values() if p["station_id"] == sid]
    page, meta = helpers.paginate(helpers.sorted_by_created(items))
    return envelope.ok_list(page, meta)


@bp.get("/api/permits/<pid>")
@require_roles(*READ_ROLES)
def get_permit(pid):
    return envelope.ok(helpers.get_or_404(db.permits, pid, "permit"), 200)


@bp.post("/api/stations/<sid>/permits/<pid>/issue")
@require_roles("ComplianceOfficer")
def issue_permit(sid, pid):
    st, p = _get_pair(sid, pid)
    if p["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "permit must be PENDING to issue")
    site = helpers.get_site(st["site_id"])
    helpers.ensure_site_open(site)
    if v.parse_date(p["expiry_date"]) <= v.parse_date(p["issued_date"]):
        raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                       "expiry_date must be after issued_date")
    p["status"] = "ISSUED"
    helpers.touch(p)
    # Cascade: the second of the station's CONSTRUCTION+FIRE permits reaching
    # ISSUED moves a PLANNED station to PERMITTED.
    if st["construction_status"] == "PLANNED":
        issued_types = {x["permit_type"] for x in db.permits.values()
                        if x["station_id"] == sid and x["status"] == "ISSUED"}
        if "CONSTRUCTION" in issued_types and "FIRE" in issued_types:
            st["construction_status"] = "PERMITTED"
            helpers.touch(st)
    return envelope.ok(p, 200)


@bp.post("/api/stations/<sid>/permits/<pid>/reject")
@require_roles("ComplianceOfficer")
def reject_permit(sid, pid):
    st, p = _get_pair(sid, pid)
    if p["status"] != "PENDING":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "permit must be PENDING to reject")
    site = helpers.get_site(st["site_id"])
    helpers.ensure_site_open(site)
    p["status"] = "REJECTED"
    helpers.touch(p)
    return envelope.ok(p, 200)
