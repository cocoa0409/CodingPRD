"""Decontamination orders, treatments and dry verification (PRD 3.6)."""

from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import calc
import services
from envelope import created, ok
from errors import ApiError
from routes._common import ALL_ROLES, listing, matches, read_pagination
from store import base_row, db, now, now_iso, parse_iso, serialize, touch
from validate import (arg_filter, opt_str, read_body, req_enum, req_int,
                      req_num, req_ref, require_auth)

bp = Blueprint("decon", __name__)

OUTCOMES = ("VERIFIED", "RETREAT", "ABANDON")
TERMINAL = ("VERIFIED", "ABANDONED")


@bp.post("/decon-orders")
def create_order():
    _user_id, _role, actor = require_auth(("Inspector",))
    body = read_body()
    record_id = req_ref(body, "inspection_record_id")
    expected_version = req_int(body, "expected_inspection_record_version")

    record = services.record_or_404(record_id)

    if record["inspection_status"] != "DECON_REQUIRED":
        raise ApiError("ERR_RECORD_NOT_AWAITING_DECON")

    if expected_version != record["version"]:
        raise ApiError("ERR_STALE_INSPECTION_RECORD_VERSION")

    services.require_active(actor)

    band = record["risk_band"]
    row = base_row()
    row.update({
        "inspection_record_id": record["id"],
        "station_id": record["station_id"],
        "treated_by_inspector_id": None,
        "verified_by_inspector_id": None,
        "status": "ORDERED",
        "attempt_count": 0,
        "band_at_order": band,
        "water_temp_f": None,
        "pressure_psi": None,
        "dwell_seconds": None,
        "treatment_started_at": None,
        "treated_at": None,
        "bay_released_at": None,
        "treatment_effectiveness_pct": None,
        "base_dry_hours": calc.BASE_DRY_HOURS[band],
        "required_dry_hours": None,
        "dry_until": None,
    })
    db.decon_orders[row["id"]] = row
    touch(record)
    return created(serialize(row))


@bp.get("/decon-orders/<oid>")
def get_order(oid):
    require_auth(ALL_ROLES)
    return ok(serialize(services.decon_order_or_404(oid)))


@bp.get("/decon-orders")
def list_orders():
    require_auth(ALL_ROLES)
    limit, offset = read_pagination()
    filters = {
        "inspection_record_id": arg_filter("inspection_record_id"),
        "station_id": arg_filter("station_id"),
        "treated_by_inspector_id": arg_filter("treated_by_inspector_id"),
        "verified_by_inspector_id": arg_filter("verified_by_inspector_id"),
        "status": arg_filter("status"),
    }
    rows = [r for r in db.decon_orders.values() if matches(r, filters)]
    return listing(rows, limit, offset)


@bp.post("/decon-orders/<oid>/treatment")
def treat_order(oid):
    _user_id, _role, actor = require_auth(("DeconTechnician",))
    body = read_body()
    water_temp_f = req_num(body, "water_temp_f", exclusive_min=0)
    pressure_psi = req_num(body, "pressure_psi", exclusive_min=0)
    dwell_seconds = req_int(body, "dwell_seconds", exclusive_min=0)

    order = services.decon_order_or_404(oid)

    if order["status"] not in ("ORDERED", "RETREAT_REQUIRED"):
        raise ApiError("ERR_DECON_ALREADY_TERMINAL")

    services.require_active(actor)
    services.require_decon_certified(actor)

    station = db.stations.get(order["station_id"])
    if (station is None or not station["hot_water_capable"]
            or station["decon_bay_count"] < 1):
        raise ApiError("ERR_STATION_NOT_HOT_WATER_CAPABLE")

    band = order["band_at_order"]
    required_dwell = calc.REQUIRED_DWELL_SECONDS[band]
    if (Decimal(str(water_temp_f)) < calc.MIN_TREATMENT_TEMP_F
            or Decimal(str(pressure_psi)) < calc.MIN_TREATMENT_PSI
            or dwell_seconds < required_dwell):
        raise ApiError("ERR_TREATMENT_BELOW_MINIMUM")

    if order["attempt_count"] >= calc.MAX_DECON_ATTEMPTS:
        raise ApiError("ERR_DECON_ATTEMPTS_EXHAUSTED")

    start = now()
    end = start + timedelta(seconds=dwell_seconds,
                            minutes=calc.BAY_BUFFER_MINUTES)
    conflicts = services.bay_conflict_count(order, station["id"], start, end)
    if conflicts >= station["decon_bay_count"]:
        raise ApiError("ERR_DECON_BAY_UNAVAILABLE")

    record = db.records.get(order["inspection_record_id"])
    services.apply_treatment(order, record, actor, water_temp_f, pressure_psi,
                             dwell_seconds)
    return ok(serialize(order))


@bp.post("/decon-orders/<oid>/dry-verification")
def verify_order(oid):
    user_id, _role, actor = require_auth(("ReleaseVerifier",))
    body = read_body()
    outcome = req_enum(body, "outcome", OUTCOMES)
    opt_str(body, "notes", min_len=None)

    order = services.decon_order_or_404(oid)

    if order["status"] in TERMINAL:
        raise ApiError("ERR_DECON_ALREADY_TERMINAL")
    if order["status"] != "TREATED":
        raise ApiError("ERR_DECON_NOT_TREATED")

    services.require_active(actor)
    services.require_verifier_certified(actor)

    if outcome in ("VERIFIED", "RETREAT"):
        dry_until = parse_iso(order["dry_until"])
        if dry_until is None or now() < dry_until:
            raise ApiError("ERR_DRY_TIME_NOT_ELAPSED")

    if user_id == order["treated_by_inspector_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    record = db.records.get(order["inspection_record_id"])
    order["verified_by_inspector_id"] = user_id

    if outcome == "VERIFIED":
        order["status"] = "VERIFIED"
        if record is not None and record["inspection_status"] == "DECON_REQUIRED":
            record["inspection_status"] = "DECON_COMPLETED"
            vessel = db.watercraft.get(record["watercraft_id"])
            if vessel is not None:
                vessel["last_decon_verified_at"] = now_iso()
                vessel["mandatory_decon_flag"] = False
                touch(vessel)
            touch(record)
    elif outcome == "RETREAT":
        order["status"] = "RETREAT_REQUIRED"
    else:
        order["status"] = "ABANDONED"
        if record is not None and record["inspection_status"] == "DECON_REQUIRED":
            record["inspection_status"] = "DECON_FAILED_ABANDONED"
            services.refund_treatment_portion(record)
            touch(record)

    touch(order)
    return ok(serialize(order))
