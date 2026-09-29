"""Storage field endpoints (PRD 3.1) and the logical clock endpoint (PRD 2.4)."""
from flask import Blueprint

import auth
import config
import engine
import envelope
import serialize
import store
import validate
from errors import ApiError, bad_request
from routes.helpers import filter_eq, list_result
from utils import D, iso

bp = Blueprint("fields", __name__)


def _validate_curve(body):
    curve = body.get("deliverability_curve")
    if not isinstance(curve, list):
        raise bad_request("deliverability_curve must be an array of curve points.")
    if len(curve) < 2 or len(curve) > 10:
        raise bad_request("deliverability_curve must carry between 2 and 10 points.")
    points = []
    previous = None
    for raw in curve:
        if not isinstance(raw, dict):
            raise bad_request("each deliverability_curve point must be an object.")
        point = {
            "inventory_pct": validate.field_number(raw, "inventory_pct", minimum=0, maximum=100),
            "withdrawal_dth_per_day": validate.field_int(raw, "withdrawal_dth_per_day", minimum=0),
            "injection_dth_per_day": validate.field_int(raw, "injection_dth_per_day", minimum=0),
        }
        if previous is not None and point["inventory_pct"] <= previous:
            raise bad_request("deliverability_curve must be strictly ascending in inventory_pct.")
        previous = point["inventory_pct"]
        points.append(point)
    if points[0]["inventory_pct"] != D(0):
        raise bad_request("the first deliverability_curve point must sit at inventory_pct 0.")
    if points[-1]["inventory_pct"] != D(100):
        raise bad_request("the last deliverability_curve point must sit at inventory_pct 100.")
    return points


@bp.post("/storage-fields")
def create_storage_field():
    auth.require([config.ROLE_FIELD_OPERATOR])
    body = validate.json_body()

    name = validate.field_str(body, "name", allow_empty=False)
    field_code = validate.field_str(body, "field_code", min_len=3, max_len=12)
    total_capacity = validate.field_number(body, "total_capacity_dth", exclusive_minimum=0)
    cushion = validate.field_number(body, "cushion_gas_dth", exclusive_minimum=0)
    if cushion >= total_capacity:
        raise bad_request("cushion_gas_dth must be strictly less than total_capacity_dth.")
    base_pressure = validate.field_int(body, "base_pressure_psig", exclusive_minimum=0)
    pressure_span = validate.field_int(body, "pressure_span_psig", exclusive_minimum=0)
    max_pressure = validate.field_int(body, "max_pressure_psig",
                                      minimum=base_pressure + pressure_span)
    curve = _validate_curve(body)
    season = validate.field_enum(body, "season", config.SEASONS, required=False,
                                 default="INJECTION")
    method = validate.field_enum(body, "deliverability_method", config.DELIVERABILITY_METHODS,
                                 required=False, default="CURVE_INTERPOLATED")
    max_working = total_capacity - cushion
    opening = validate.field_number(body, "opening_working_gas_dth", required=False,
                                    default=D(0), minimum=0, maximum=max_working)

    for existing in store.storage_fields.values():
        if existing["field_code"] == field_code:
            raise ApiError("ERR_DUPLICATE_FIELD_CODE",
                           "field_code %s already exists." % field_code)

    field = store.new_record()
    field.update({
        "name": name,
        "field_code": field_code,
        "season": season,
        "total_capacity_dth": total_capacity,
        "cushion_gas_dth": cushion,
        "max_working_gas_dth": max_working,
        "working_gas_inventory_dth": D(opening),
        "opening_working_gas_dth": D(opening),
        "fuel_gas_used_dth": D(0),
        "retained_fuel_pool_dth": D(0),
        "inventory_pct": D(0),
        "base_pressure_psig": base_pressure,
        "pressure_span_psig": pressure_span,
        "max_pressure_psig": max_pressure,
        "current_pressure_psig": base_pressure,
        "deliverability_curve": curve,
        "deliverability_method": method,
        "deliverability_tier": "TIER_1",
        "max_withdrawal_rate_dth_per_day": 0,
        "max_injection_rate_dth_per_day": 0,
        "wells_in_service_count": 0,
        "field_posture": "FROZEN",
    })
    engine.recompute_derived(field)
    store.put("StorageField", field)
    return envelope.created(serialize.storage_field(field))


@bp.get("/storage-fields/<field_id>")
def read_storage_field(field_id):
    auth.require(config.ALL_ROLES)
    field = validate.resolve_path("StorageField", field_id)
    return envelope.object_response(serialize.storage_field(field))


@bp.post("/storage-fields/<field_id>/season")
def turn_season(field_id):
    auth.require([config.ROLE_FIELD_OPERATOR])
    body = validate.json_body()
    season = validate.field_enum(body, "season", config.SEASONS)
    field = validate.resolve_path("StorageField", field_id)

    field["season"] = season
    store.touch(field)
    engine.phase_a_season(field, season)
    return envelope.object_response(serialize.storage_field(field))


@bp.get("/storage-fields/<field_id>/regulatory-reports")
def list_field_reports(field_id):
    auth.require(config.STAFF_ROLES)
    limit, offset = validate.pagination()
    report_type = validate.query_enum("report_type", config.REPORT_TYPES)
    status = validate.query_enum("status", config.REPORT_STATUSES)
    field = validate.resolve_path("StorageField", field_id)

    rows = store.reports_of_field(field["id"])
    rows = filter_eq(rows, "report_type", report_type)
    rows = filter_eq(rows, "status", status)
    return list_result(rows, serialize.report, limit, offset)


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.require(config.STAFF_ROLES)
    body = validate.json_body()
    instant = validate.field_instant(body, "to_iso8601")
    store.set_clock(instant)
    return envelope.object_response({"current_utc": iso(store.now())})
