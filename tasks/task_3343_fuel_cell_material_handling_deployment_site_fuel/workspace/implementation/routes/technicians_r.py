"""Technician registry endpoints (PRD section 3.4)."""

from flask import Blueprint

import db
import envelope
import helpers
import validators as v
from authz import require_roles
from errors import ApiError, ERR_INVALID_DATE_RANGE

bp = Blueprint("technicians", __name__)

READ_ROLES = ("SiteManager", "ConversionTechnician", "PlatformAdmin")
CERT_LEVELS = ("BASIC", "ADVANCED", "MASTER")


@bp.post("/api/technicians")
@require_roles("PlatformAdmin")
def create_technician():
    data = v.body()
    name = v.str_value(v.req(data, "name"), "name", 1, 120)
    level = v.enum_value(v.req(data, "certification_level"),
                         "certification_level", CERT_LEVELS)
    until = v.date_value(v.req(data, "certified_until"), "certified_until")
    active = True
    if "active" in data and data["active"] is not None:
        active = v.bool_value(data["active"], "active")
    if v.parse_date(until) <= db.current_date():
        raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                       "certified_until must be a future date")
    t = helpers.create_rec(db.technicians, {
        "name": name,
        "certification_level": level,
        "certified_until": until,
        "active": active,
    })
    return envelope.ok(t, 201)


@bp.get("/api/technicians")
@require_roles(*READ_ROLES)
def list_technicians():
    page, meta = helpers.paginate(
        helpers.sorted_by_created(list(db.technicians.values())))
    return envelope.ok_list(page, meta)


@bp.get("/api/technicians/<tid>")
@require_roles(*READ_ROLES)
def get_technician(tid):
    return envelope.ok(helpers.get_or_404(db.technicians, tid,
                                          "technician"), 200)


@bp.get("/api/technicians/<tid>/conversion-events")
@require_roles(*READ_ROLES)
def list_technician_events(tid):
    helpers.get_or_404(db.technicians, tid, "technician")
    items = [e for e in db.events.values() if e["technician_id"] == tid]
    page, meta = helpers.paginate(helpers.sorted_by_created(items))
    return envelope.ok_list(page, meta)
