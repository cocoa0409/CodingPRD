"""Logical clock, site summary, and filtered Sites list."""

from flask import Blueprint

from auth import require_roles
from db import DB
from errors import err, ok_list, ok_object
from helpers import apply_filters, get_body, paged, parse_iso, iso_of
from services import effects
from validate import get_site

bp = Blueprint("misc", __name__)

SITE_READ = ("NetworkArchitect", "RFEngineer", "SpectrumCoordinator", "SpectrumRegulator", "FieldTechnician")
SUMMARY_READ = ("NetworkArchitect", "RFEngineer", "SpectrumCoordinator", "FieldTechnician")


@bp.post("/_clock/set_current_utc")
def set_clock():
    require_roles("NetworkArchitect")
    body = get_body()
    target = body.get("to_iso8601")
    if target is None:
        raise err("ERR_INVALID_REQUEST", "to_iso8601 is required")
    dt = parse_iso(target, "to_iso8601")
    DB.clock = dt
    effects.reevaluate_clock()
    return ok_object({"current_utc": iso_of(DB.clock)})


@bp.get("/sites")
def list_sites_flat():
    require_roles(*SITE_READ)
    items = list(DB.sites.values())
    items = apply_filters(items, [("enterprise_id", "enterprise_id"), ("status", "status"), ("posture", "posture")])
    window, total, limit, offset = paged(items)
    return ok_list(window, total, limit, offset)


@bp.get("/sites/<sid>/summary")
def site_summary(sid):
    require_roles(*SUMMARY_READ)
    site = get_site(sid)
    design = next((d for d in DB.designs.values()
                   if d["site_id"] == sid and d["status"] == "APPROVED"), None)
    open_alerts = sum(1 for a in DB.alerts.values()
                      if a["site_id"] == sid and a["status"] in ("OPEN", "ACKNOWLEDGED", "MITIGATING"))
    active_slices = sum(1 for s in DB.slices.values()
                        if s["site_id"] == sid and s["status"] == "ACTIVATED")
    summary = {
        "site_id": sid,
        "posture": site["posture"],
        "status": site["status"],
        "capacity_shortfall_mbps": design.get("capacity_shortfall_mbps") if design else None,
        "spectrum_utilization_mhz": site["spectrum_utilization_mhz"],
        "device_count": site["device_count"],
        "open_alert_count": open_alerts,
        "active_slice_count": active_slices,
    }
    return ok_object(summary)
