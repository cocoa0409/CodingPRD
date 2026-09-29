"""Compressor unit and run endpoints (PRD 3.3)."""
from flask import Blueprint

import auth
import config
import engine
import envelope
import serialize
import store
import validate
from errors import ApiError
from routes.helpers import filter_eq, list_result
from utils import D

bp = Blueprint("compressors", __name__)


@bp.post("/compressor-units")
def create_unit():
    auth.require([config.ROLE_FIELD_OPERATOR])
    body = validate.json_body()

    field_id = validate.field_id(body, "storage_field_id")
    unit_code = validate.field_str(body, "unit_code", allow_empty=False)
    rated_horsepower = validate.field_int(body, "rated_horsepower", exclusive_minimum=0)
    derate_factor = validate.field_number(body, "derate_factor", required=False, default=D("0.00"),
                                          minimum="0.00", maximum="0.50")

    field = validate.resolve_body_fk("StorageField", field_id)

    for existing in store.units_of_field(field["id"]):
        if existing["unit_code"] == unit_code:
            raise ApiError("ERR_DUPLICATE_UNIT_CODE",
                           "unit_code %s already exists on this field." % unit_code)

    unit = store.new_record()
    unit.update({
        "storage_field_id": field["id"],
        "unit_code": unit_code,
        "rated_horsepower": rated_horsepower,
        "derate_factor": D(derate_factor),
        "status": "AVAILABLE",
        "lifetime_fuel_dth": D(0),
        "scheduled_run_count": 0,
    })
    store.put("CompressorUnit", unit)
    return envelope.created(serialize.compressor_unit(unit))


@bp.get("/compressor-units")
def list_units():
    auth.require(config.STAFF_ROLES)
    limit, offset = validate.pagination()
    field_id = validate.query_id("storage_field_id")
    status = validate.query_enum("status", config.UNIT_STATUSES)

    rows = store.values("CompressorUnit")
    rows = filter_eq(rows, "storage_field_id", field_id)
    rows = filter_eq(rows, "status", status)
    return list_result(rows, serialize.compressor_unit, limit, offset)


@bp.get("/compressor-units/<unit_id>")
def read_unit(unit_id):
    auth.require(config.STAFF_ROLES)
    unit = validate.resolve_path("CompressorUnit", unit_id)
    return envelope.object_response(serialize.compressor_unit(unit))


@bp.get("/compressor-units/<unit_id>/runs")
def list_unit_runs(unit_id):
    auth.require(config.STAFF_ROLES)
    limit, offset = validate.pagination()
    status = validate.query_enum("status", config.RUN_STATUSES)
    unit = validate.resolve_path("CompressorUnit", unit_id)

    rows = store.runs_of_unit(unit["id"])
    rows = filter_eq(rows, "status", status)
    return list_result(rows, serialize.compressor_run, limit, offset)


@bp.post("/compressor-runs")
def create_run():
    auth.require([config.ROLE_FIELD_OPERATOR])
    body = validate.json_body()

    unit_id = validate.field_id(body, "compressor_unit_id")
    start = validate.field_instant(body, "window_start_at")
    end = validate.field_instant(body, "window_end_at")
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "window_end_at must be strictly after window_start_at.")
    allocated = validate.field_int(body, "allocated_horsepower", exclusive_minimum=0)
    mode = validate.field_enum(body, "mode", config.RUN_MODES)

    unit = validate.resolve_body_fk("CompressorUnit", unit_id)
    field = store.storage_fields[unit["storage_field_id"]]

    if field["field_posture"] == "FROZEN":
        raise ApiError("ERR_FIELD_FROZEN", "no run may be booked on a frozen field.")
    if start < store.now():
        raise ApiError("ERR_RUN_WINDOW_IN_PAST",
                       "window_start_at may not begin before the current clock.")
    if engine.horsepower_oversubscribed(unit, start, end, allocated):
        raise ApiError("ERR_HORSEPOWER_OVERSUBSCRIBED",
                       "the unit's rated horsepower cannot carry this allocation.")

    duration, effective, ratio, band = engine.run_booking_figures(unit, start, end, allocated)
    run = store.new_record()
    run.update({
        "compressor_unit_id": unit["id"],
        "window_start_at": start,
        "window_end_at": end,
        "allocated_horsepower": allocated,
        "mode": mode,
        "duration_hours": duration,
        "effective_horsepower": effective,
        "utilization_ratio": ratio,
        "utilization_band": band,
        "fuel_consumed_dth": None,
        "status": "SCHEDULED",
    })
    store.put("CompressorRun", run)

    unit["scheduled_run_count"] = int(unit["scheduled_run_count"]) + 1
    unit["status"] = "COMMITTED"
    store.touch(unit)
    return envelope.created(serialize.compressor_run(run))


@bp.post("/compressor-runs/<run_id>/complete")
def complete_run(run_id):
    auth.require([config.ROLE_FIELD_OPERATOR])
    validate.json_body(required=False)
    run = validate.resolve_path("CompressorRun", run_id)
    unit = store.compressor_units[run["compressor_unit_id"]]

    if run["status"] != "SCHEDULED" or unit["status"] == "OUT_OF_SERVICE":
        raise ApiError("ERR_INVALID_RUN_STATE",
                       "only a SCHEDULED run on an in-service unit may be completed.")
    if store.now() < run["window_end_at"]:
        raise ApiError("ERR_RUN_WINDOW_NOT_ELAPSED", "the run window has not yet elapsed.")

    fuel = engine.compressor_fuel_burn(run)
    run["fuel_consumed_dth"] = fuel
    run["status"] = "COMPLETED"
    store.touch(run)

    unit["lifetime_fuel_dth"] = D(unit["lifetime_fuel_dth"]) + fuel
    unit["scheduled_run_count"] = int(unit["scheduled_run_count"]) - 1
    if unit["scheduled_run_count"] == 0:
        unit["status"] = "AVAILABLE"
    store.touch(unit)

    field = store.storage_fields[unit["storage_field_id"]]
    field["fuel_gas_used_dth"] = D(field["fuel_gas_used_dth"]) + fuel
    field["working_gas_inventory_dth"] = D(field["working_gas_inventory_dth"]) - fuel
    before, after = engine.refresh_field(field, force_touch=True)
    engine.phase_b(field, before, after, "compressor fuel burn %s" % engine.today_str())
    return envelope.object_response(serialize.compressor_run(run))
