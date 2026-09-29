"""PRD 3.4 — the immutable cable selection catalogue."""

from flask import Blueprint, request

import calc
import lookup
import serial
from auth import (CERTIFIER, CLIENT, DESIGN_ENGINEER, INSTALLER, PROJECT_MANAGER,
                  TEST_TECHNICIAN, require)
from envelope import created, enum_filter, ok, paginate
from store import base_record, db
from validation import Field, body

cables_bp = Blueprint("cables", __name__)

READ_ROLES = (PROJECT_MANAGER, DESIGN_ENGINEER, INSTALLER, TEST_TECHNICIAN,
              CERTIFIER, CLIENT)


@cables_bp.route("/cabling/cable-types", methods=["POST"])
@require(DESIGN_ENGINEER)
def register_cable_type():
    values = body([
        Field("category", "enum", enum=calc.CATEGORIES),
        Field("jacket_rating", "enum", enum=calc.JACKET_RATINGS),
        Field("outer_diameter_mm", "number", exclusive_min=0),
        Field("max_channel_length_m", "number", exclusive_min=0),
        Field("shielded", "bool", required=False, default=False),
        Field("cost_per_meter_cents", "integer", minimum=0),
        Field("applications", "array", min_len=1, item_enum=calc.APPLICATIONS),
    ])
    cable_type = base_record(versioned=False)
    cable_type.update({
        "category": values["category"],
        "jacket_rating": values["jacket_rating"],
        "outer_diameter_mm": values["outer_diameter_mm"],
        "cross_section_area_sq_mm": calc.cross_section_area_sq_mm(
            values["outer_diameter_mm"]),
        "max_channel_length_m": values["max_channel_length_m"],
        "shielded": values["shielded"],
        "cost_per_meter_cents": values["cost_per_meter_cents"],
        "applications": values["applications"],
    })
    db.cable_types[cable_type["id"]] = cable_type
    return created(serial.public(cable_type))


@cables_bp.route("/cabling/cable-types/<cable_type_id>", methods=["GET"])
@require(*READ_ROLES)
def read_cable_type(cable_type_id):
    return ok(serial.public(lookup.cable_type(cable_type_id)))


@cables_bp.route("/cabling/cable-types", methods=["GET"])
@require(*READ_ROLES)
def list_cable_types():
    category = enum_filter(request.args, "category", calc.CATEGORIES)
    jacket_rating = enum_filter(request.args, "jacket_rating", calc.JACKET_RATINGS)
    rows = []
    for cable_type in db.cable_types.values():
        if category is not None and cable_type["category"] != category:
            continue
        if jacket_rating is not None and cable_type["jacket_rating"] != jacket_rating:
            continue
        rows.append(cable_type)
    return paginate(rows, request.args, serial.public)
