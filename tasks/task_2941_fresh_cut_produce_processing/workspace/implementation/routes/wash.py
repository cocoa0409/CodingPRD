"""Wash systems, antimicrobial readings and water change-outs."""

from decimal import Decimal

from flask import Blueprint

import db
import serializers
from envelope import actor, bool_param, listing, object_response, read_body, require
from errors import ApiError
from services import chemistry
from util import now_dt

bp = Blueprint("wash", __name__)

CREATE_SYSTEM = (
    ("system_code", "str", True),
    ("water_volume_gal", "num", True, {"gt": Decimal(0)}),
    ("max_concurrent_runs", "int", True, {"ge": 1}),
)

CREATE_READING = (
    ("reading_at", "datetime", True),
    ("free_chlorine_ppm", "num", True, {"ge": Decimal(0)}),
    ("ph", "num", True, {"gt": Decimal(0), "le": Decimal(14)}),
    ("orp_mv", "int", True),
    ("turbidity_ntu", "num", True, {"ge": Decimal(0)}),
)


@bp.post("/wash-systems")
@require("PlantAdmin")
def create_system():
    body = read_body(CREATE_SYSTEM)
    for existing in db.rows("wash_systems"):
        if existing["system_code"] == body["system_code"]:
            raise ApiError(
                "ERR_DUPLICATE_CODE", "wash system code is already registered"
            )
    row = db.new_row(
        "wash_systems",
        {
            "system_code": body["system_code"],
            "water_volume_gal": body["water_volume_gal"],
            "max_concurrent_runs": body["max_concurrent_runs"],
            "status": "IN_SERVICE",
            "weighted_load_lb": Decimal("0.00"),
            "organic_load_index": Decimal("0.000"),
            "target_free_chlorine_ppm": Decimal("20.0"),
            "changeout_count": 0,
            "reading_sequence_high_water": 0,
        },
    )
    db.stamp(row, "last_changeout_at", now_dt())
    return object_response(serializers.wash_system(row), 201)


@bp.get("/wash-systems/<system_id>")
@require(
    "PlantAdmin", "QAManager", "QATechnician", "LineOperator", "SanitationTech"
)
def get_system(system_id):
    row = db.get_or_404("wash_systems", system_id)
    return object_response(serializers.wash_system(row))


@bp.post("/wash-systems/<system_id>/antimicrobial-readings")
@require("LineOperator", "SanitationTech")
def create_reading(system_id):
    body = read_body(CREATE_READING)
    system = db.get_or_404("wash_systems", system_id)
    sequence_no = system["reading_sequence_high_water"] + 1
    reading = db.new_row(
        "readings",
        {
            "wash_system_id": system_id,
            "sequence_no": sequence_no,
            "free_chlorine_ppm": body["free_chlorine_ppm"],
            "ph": body["ph"],
            "orp_mv": body["orp_mv"],
            "turbidity_ntu": body["turbidity_ntu"],
            "taken_by_user_id": actor(),
            "organic_load_index_at_reading": None,
            "target_free_chlorine_ppm_at_reading": None,
            "topup_ppm_required": None,
            "below_target": False,
        },
        common=False,
    )
    db.set_instant(reading, "reading_at", body["reading_at"])

    system["reading_sequence_high_water"] = sequence_no
    result = chemistry.compute_chemistry(system)
    system["weighted_load_lb"] = result["weighted_load_lb"]
    system["organic_load_index"] = result["organic_load_index"]
    system["target_free_chlorine_ppm"] = result["target_free_chlorine_ppm"]
    if result["dump_required"] and system["status"] == "IN_SERVICE":
        system["status"] = "DUMP_REQUIRED"
    db.touch(system)

    target = result["target_free_chlorine_ppm"]
    reading["organic_load_index_at_reading"] = result["organic_load_index"]
    reading["target_free_chlorine_ppm_at_reading"] = target
    reading["topup_ppm_required"] = chemistry.topup_for(
        target, reading["free_chlorine_ppm"]
    )
    reading["below_target"] = (
        target is not None and reading["free_chlorine_ppm"] < target
    )
    return object_response(serializers.reading(reading), 201)


@bp.get("/wash-systems/<system_id>/antimicrobial-readings")
@require(
    "PlantAdmin", "QAManager", "QATechnician", "LineOperator", "SanitationTech"
)
def list_readings(system_id):
    below = bool_param("below_target")
    db.get_or_404("wash_systems", system_id)
    rows = [r for r in db.rows("readings") if r["wash_system_id"] == system_id]
    if below is not None:
        rows = [r for r in rows if r["below_target"] == below]
    rows.sort(key=lambda r: (db.dt_of(r, "reading_at"), r["sequence_no"]), reverse=True)
    return listing(rows, serializers.reading)


@bp.post("/wash-systems/<system_id>/changeout")
@require("SanitationTech")
def changeout(system_id):
    system = db.get_or_404("wash_systems", system_id)
    chemistry.changeout(system, now_dt())
    return object_response(serializers.wash_system(system))
