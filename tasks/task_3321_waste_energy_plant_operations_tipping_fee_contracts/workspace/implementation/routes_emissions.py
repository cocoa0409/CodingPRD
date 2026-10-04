"""Emissions permits and readings."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from auth import require_role
from db import store
from errors import err_422, err_invalid_state, err_not_found, err_invalid_request
from helpers import (body_json, new_entity, parse_dt, require_fields, success_list,
                     success_obj, to_decimal, to_int, touch, round6)
from serializers import permit_out, reading_out

bp = Blueprint("emissions", __name__)

EO = ["EnvironmentalOfficer"]
READERS = ["EnvironmentalOfficer", "PlantOperator", "Regulator"]
READERS_R = ["EnvironmentalOfficer", "Regulator"]
REG = ["Regulator"]


@bp.post("/wte/emissions-permits")
def create_permit():
    require_role(EO)
    b = body_json()
    require_fields(b, ["pollutant", "hourly_limit", "daily_limit"])
    pollutant = b["pollutant"]
    if not isinstance(pollutant, str) or not pollutant:
        raise err_invalid_request("pollutant must be a non-empty string")
    for p in store.emissions_permits.values():
        if p["pollutant"] == pollutant and p["status"] == "ACTIVE":
            raise err_422("ERR_DUPLICATE_PERMIT",
                          "an ACTIVE permit already exists for this pollutant")
    hourly = to_decimal(b["hourly_limit"], "hourly_limit")
    daily = to_decimal(b["daily_limit"], "daily_limit")
    window = b.get("rolling_avg_window_hours", 24)
    window = to_int(window, "rolling_avg_window_hours")
    if window <= 0:
        raise err_invalid_request("rolling_avg_window_hours must be > 0")
    p = new_entity({
        "pollutant": pollutant,
        "hourly_limit": hourly,
        "daily_limit": daily,
        "rolling_avg_window_hours": window,
        "status": "ACTIVE",
    })
    store.emissions_permits[p["id"]] = p
    return success_obj(permit_out(p), 201)


@bp.get("/wte/emissions-permits")
def list_permits():
    require_role(READERS)
    items = sorted(store.emissions_permits.values(), key=lambda x: (x["created_at"], x["id"]))
    q = request.args.get("pollutant")
    if q is not None:
        items = [p for p in items if p["pollutant"] == q]
    q = request.args.get("status")
    if q is not None:
        items = [p for p in items if p["status"] == q]
    return success_list([permit_out(p) for p in items])


@bp.get("/wte/emissions-permits/<pid>")
def get_permit(pid):
    require_role(READERS)
    p = store.emissions_permits.get(pid)
    if p is None:
        raise err_not_found("permit not found")
    return success_obj(permit_out(p))


@bp.post("/wte/emissions-permits/<pid>/suspend")
def suspend_permit(pid):
    require_role(REG)
    p = store.emissions_permits.get(pid)
    if p is None:
        raise err_not_found("permit not found")
    if p["status"] != "ACTIVE":
        raise err_invalid_state("permit is not ACTIVE")
    p["status"] = "SUSPENDED"
    touch(p)
    return success_obj(permit_out(p))


@bp.post("/wte/emissions-readings")
def create_reading():
    require_role(EO)
    b = body_json()
    require_fields(b, ["permit_id", "value", "measured_at"])
    p = store.emissions_permits.get(b["permit_id"])
    if p is None:
        raise err_not_found("permit not found")
    if p["status"] != "ACTIVE":
        raise err_invalid_state("permit is not ACTIVE")
    value = to_decimal(b["value"], "value")
    if value <= 0:
        raise err_invalid_request("value must be > 0")
    measured_at = parse_dt(b["measured_at"], "measured_at")
    # Exceedance: hourly breach (strictly >) OR rolling daily average breach
    hourly_breach = value > p["hourly_limit"]
    window_start = measured_at - timedelta(hours=p["rolling_avg_window_hours"])
    window_values = [r["value"] for r in store.emissions_readings.values()
                     if r["permit_id"] == p["id"]
                     and window_start <= r["measured_at"] <= measured_at]
    window_values.append(value)
    avg = round6(sum(window_values, Decimal("0")) / Decimal(len(window_values)))
    daily_breach = avg > p["daily_limit"]
    r = new_entity({
        "permit_id": p["id"],
        "value": value,
        "measured_at": measured_at,
        "exceedance": bool(hourly_breach or daily_breach),
    })
    store.emissions_readings[r["id"]] = r
    return success_obj(reading_out(r), 201)


@bp.get("/wte/emissions-readings")
def list_readings():
    require_role(READERS_R)
    items = sorted(store.emissions_readings.values(), key=lambda x: (x["created_at"], x["id"]))
    q = request.args.get("permit_id")
    if q is not None:
        items = [r for r in items if r["permit_id"] == q]
    return success_list([reading_out(r) for r in items])


@bp.get("/wte/emissions-readings/<rid>")
def get_reading(rid):
    require_role(READERS_R)
    r = store.emissions_readings.get(rid)
    if r is None:
        raise err_not_found("reading not found")
    return success_obj(reading_out(r))
