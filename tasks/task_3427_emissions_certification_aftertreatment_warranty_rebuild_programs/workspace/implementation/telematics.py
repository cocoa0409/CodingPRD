"""Telematics snapshot ingestion + fault prediction (PRD §3.5)."""
from flask import Blueprint

import calculations
import store
from errors import ApiError
from rbac import auth, ANY
from validators import (
    body, f_int, f_num, f_dt, get_or_404, page_args, slice_page,
    envelope_ok, new_append, touch, ser,
)

bp = Blueprint("telematics", __name__)

SEVERITIES = ("CRITICAL", "MAJOR", "MINOR")


def _fault_codes(b):
    fc = b.get("fault_codes")
    if fc is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Missing required field: fault_codes")
    if not isinstance(fc, list):
        raise ApiError("ERR_INVALID_REQUEST", 400, "fault_codes must be a list")
    out = []
    for e in fc:
        if (not isinstance(e, dict) or not isinstance(e.get("code"), str)
                or e.get("severity") not in SEVERITIES):
            raise ApiError(
                "ERR_INVALID_REQUEST", 400,
                "each fault_codes entry must carry a string code and severity CRITICAL|MAJOR|MINOR")
        out.append({"code": e["code"], "severity": e["severity"]})
    return out


@bp.post("/emissions/engine-units/<unitId>/telematics-snapshots")
def ingest_snapshot(unitId):
    auth(("PlatformAdmin",))
    b = body()
    recorded_at = f_dt(b, "recorded_at")
    odometer = f_int(b, "odometer_miles")
    hours = f_int(b, "engine_hours")
    fault_codes = _fault_codes(b)
    def_gal = f_num(b, "def_consumption_gal")
    drift = f_num(b, "nox_sensor_drift_ppm")
    unit = get_or_404(store.units, unitId, "EngineUnit")
    # temporal (priority 12): odometer/hours monotonic, then strictly-later timestamp
    if odometer < unit["accumulated_miles"] or hours < unit["accumulated_hours"]:
        raise ApiError("ERR_NON_MONOTONIC_ODOMETER", 409,
                       "Snapshot readings must not go below the unit's accumulated values")
    if unit["last_snapshot_at"] is not None and not (recorded_at > unit["last_snapshot_at"]):
        raise ApiError("ERR_NON_MONOTONIC_TELEMATICS", 409,
                       "recorded_at must be strictly after the latest snapshot")
    miles_before = unit["accumulated_miles"]
    score = calculations.fault_risk_score(
        fault_codes, drift, def_gal, miles_before, odometer)
    snap = new_append()
    snap.update({
        "engine_unit_id": unit["id"],
        "recorded_at": recorded_at,
        "odometer_miles": odometer,
        "engine_hours": hours,
        "fault_codes": fault_codes,
        "def_consumption_gal": def_gal,
        "nox_sensor_drift_ppm": drift,
        "fault_risk_score": score,
    })
    store.snapshots[snap["id"]] = snap
    unit["accumulated_miles"] = odometer
    unit["accumulated_hours"] = hours
    unit["last_snapshot_at"] = recorded_at
    if score >= calculations.PREDICTIVE_SERVICE_THRESHOLD:
        unit["predictive_service_due"] = True  # advisory latch, never cleared
    touch(unit)
    return envelope_ok(ser(snap), 201)


@bp.get("/emissions/engine-units/<unitId>/telematics-snapshots")
def list_snapshots(unitId):
    auth(ANY)
    limit, offset = page_args()
    get_or_404(store.units, unitId, "EngineUnit")
    items = [s for s in store.snapshots.values() if s["engine_unit_id"] == unitId]
    page, meta = slice_page(items, limit, offset)
    return envelope_ok(page, 200, meta)
