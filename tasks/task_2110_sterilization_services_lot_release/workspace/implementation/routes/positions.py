"""Load-map slots, indicator placement and indicator read-out."""

from decimal import Decimal

from flask import Blueprint, request

import clock
import response
import validation as V
from db import db
from errors import ApiError
from middleware import authenticate
from routes.common import fetch, paginate, peek
from services.domain import (indicators_of_position, new_record, touch)

bp = Blueprint("positions", __name__)

INDICATOR_TYPES = ("DOSIMETER", "BIOLOGICAL")
PLACEMENT_ZONES = ("MIN_DOSE", "MAX_DOSE", "ROUTINE")


@bp.get("/sterilization/load-positions/<position_id>")
def read_load_position(position_id):
    authenticate("CycleOperator", "DosimetryAnalyst", "QualityReleaseOfficer",
                 "RegulatoryAdmin")
    return response.object_response(fetch("load_positions", position_id))


@bp.get("/sterilization/load-positions")
def list_load_positions():
    authenticate("CycleOperator", "DosimetryAnalyst", "QualityReleaseOfficer",
                 "RegulatoryAdmin")
    limit, offset = V.pagination()
    cycle_id = request.args.get("cycle_id")
    lot_id = request.args.get("lot_id")
    rows = [
        p for p in db.load_positions.values()
        if (cycle_id is None or p["cycle_id"] == cycle_id)
        and (lot_id is None or p["lot_id"] == lot_id)
    ]
    page, total = paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.post("/sterilization/load-positions/<position_id>/indicators")
def place_indicator(position_id):
    authenticate("CycleOperator")
    body = V.body()
    indicator_type = V.req_enum(body, "indicator_type", INDICATOR_TYPES)
    placement_zone = V.req_enum(body, "placement_zone", PLACEMENT_ZONES)
    serial_code = V.req_string(body, "serial_code", 1, 32)
    if indicator_type == "BIOLOGICAL":
        spore_population = V.req_int(body, "spore_population", minimum=1)
    else:
        if V.present(body, "spore_population"):
            raise ApiError("ERR_VALIDATION",
                           "spore_population is forbidden for a DOSIMETER indicator.")
        spore_population = None

    preview = peek("load_positions", position_id)
    if preview is not None and placement_zone == "MIN_DOSE" and preview["zone"] != "MIN_DOSE":
        raise ApiError("ERR_VALIDATION",
                       "A MIN_DOSE indicator may only sit in a MIN_DOSE slot.")

    position = fetch("load_positions", position_id)

    for existing in db.indicators.values():
        if existing["serial_code"] == serial_code:
            raise ApiError("ERR_DUPLICATE_CODE",
                           "serial_code '%s' is already registered." % serial_code)

    indicator = new_record({
        "load_position_id": position["id"],
        "indicator_type": indicator_type,
        "placement_zone": placement_zone,
        "serial_code": serial_code,
        "spore_population": spore_population,
        "measured_dose_kgy": None,
        "bi_result": "PENDING",
        "reading_status": "UNREAD",
        "read_at": None,
        "read_by_user_id": None,
    })
    db.indicators[indicator["id"]] = indicator
    return response.object_response(indicator, 201)


@bp.get("/sterilization/load-positions/<position_id>/indicators")
def list_position_indicators(position_id):
    authenticate("CycleOperator", "DosimetryAnalyst", "QualityReleaseOfficer",
                 "RegulatoryAdmin")
    limit, offset = V.pagination()
    fetch("load_positions", position_id)
    rows = indicators_of_position(position_id)
    page, total = paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.post("/sterilization/indicators/<indicator_id>/reading")
def record_reading(indicator_id):
    user_id, _role = authenticate("DosimetryAnalyst")
    body = V.body()

    preview = peek("indicators", indicator_id)
    has_dose = V.present(body, "measured_dose_kgy")
    has_bi = V.present(body, "bi_result")
    if has_dose == has_bi:
        raise ApiError("ERR_VALIDATION",
                       "Exactly one of measured_dose_kgy or bi_result must be supplied.")
    measured = None
    bi_result = None
    if has_dose:
        measured = V.req_number(body, "measured_dose_kgy", gt=0)
        if preview is not None and preview["indicator_type"] != "DOSIMETER":
            raise ApiError("ERR_VALIDATION",
                           "measured_dose_kgy may only be supplied for a DOSIMETER indicator.")
    else:
        bi_result = V.req_enum(body, "bi_result", ("NEGATIVE", "POSITIVE"))
        if preview is not None and preview["indicator_type"] != "BIOLOGICAL":
            raise ApiError("ERR_VALIDATION",
                           "bi_result may only be supplied for a BIOLOGICAL indicator.")

    indicator = fetch("indicators", indicator_id)
    position = db.load_positions.get(indicator["load_position_id"])
    cycle = db.cycles.get(position["cycle_id"]) if position else None

    # priority 45 - a re-read is only documented on a deviated cycle
    if indicator["reading_status"] == "READ" \
            and (cycle is None or cycle["status"] != "DOSE_DEVIATION"):
        raise ApiError("ERR_INDICATOR_ALREADY_READ")

    if has_dose:
        indicator["measured_dose_kgy"] = measured
    else:
        indicator["bi_result"] = bi_result
    indicator["reading_status"] = "READ"
    indicator["read_at"] = clock.now()
    indicator["read_by_user_id"] = user_id
    touch(indicator)

    if cycle is not None:
        if cycle["status"] == "COMPLETED":
            cycle["status"] = "DOSIMETRY_REVIEW"
            touch(cycle)
        elif cycle["status"] == "DOSE_DEVIATION":
            cycle["deviation_code"] = "NONE"
            cycle["delivered_dose_kgy"] = None
            cycle["max_observed_dose_kgy"] = None
            cycle["status"] = "DOSIMETRY_REVIEW"
            touch(cycle)

    return response.object_response(indicator)
