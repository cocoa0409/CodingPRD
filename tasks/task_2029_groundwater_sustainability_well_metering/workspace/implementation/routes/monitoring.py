"""MonitoringReading endpoints."""
from flask import Blueprint

from db import store, new_id, stamp_reading
from errors import err
from middleware import ALL_ROLES, require_roles, body, paginate, sort_default
from response import ok, ok_list
from serializers import ser_reading
from util import round2, to_decimal, dp_ok, parse_iso_datetime

bp = Blueprint("monitoring", __name__)


@bp.post("/monitoring-readings")
def create_reading():
    require_roles("WaterMaster")
    b = body()
    wid = b.get("well_id")
    if not isinstance(wid, str) or not wid:
        raise err("ERR_INVALID_REQUEST", "well_id is required")
    measured = parse_iso_datetime(b.get("measured_at"))
    if measured is None:
        raise err("ERR_INVALID_REQUEST", "measured_at must be an ISO 8601 UTC instant")
    if measured > store.clock:
        raise err("ERR_INVALID_REQUEST", "measured_at must not be after the logical clock")
    depth = to_decimal(b.get("depth_to_water_ft"))
    if depth is None or depth <= 0 or not dp_ok(depth, 2):
        raise err("ERR_INVALID_REQUEST", "depth_to_water_ft must be > 0 with at most 2 decimal places")
    collector = b.get("collector_name")
    if not isinstance(collector, str):
        raise err("ERR_INVALID_REQUEST", "collector_name is required")
    w = store.wells.get(wid)
    if w is None:
        raise err("ERR_WELL_NOT_FOUND", "No Well with the given id")
    # Well ACTIVE (priority 8) before the well-type gate (priority 16).
    if w["status"] != "ACTIVE":
        raise err("ERR_WELL_NOT_ACTIVE", "Well must be ACTIVE to accept monitoring readings")
    if w["well_type"] != "MONITORING":
        raise err("ERR_INVALID_WELL_TYPE", "Monitoring readings apply only to MONITORING wells")
    r = {
        "id": new_id(),
        "well_id": w["id"],
        "measured_at": measured,
        "depth_to_water_ft": round2(depth),
        "collector_name": collector,
    }
    stamp_reading(r)
    store.readings[r["id"]] = r
    return ok(ser_reading(r), status=201)


@bp.get("/wells/<well_id>/monitoring-readings")
def list_readings(well_id):
    require_roles(*ALL_ROLES)
    w = store.wells.get(well_id)
    if w is None:
        raise err("ERR_WELL_NOT_FOUND", "No Well with the given id")
    items = [r for r in store.readings.values() if r["well_id"] == well_id]
    items = sort_default(items)
    page, pg = paginate(items)
    return ok_list([ser_reading(r) for r in page], pg)
