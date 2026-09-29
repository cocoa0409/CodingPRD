"""Field registration, survey confirmation and practice history."""

from decimal import Decimal

from flask import Blueprint

import db
import middleware as mw
import response as resp
import validators as v
from services import calc, common, serialize

bp = Blueprint("fields", __name__)

SOIL_GROUPS = ("LOAM", "CLAY", "SAND")
PRACTICE_CODES = ("COVER_CROP", "REDUCED_TILLAGE", "NUTRIENT_MANAGEMENT")
EVIDENCE_SOURCES = ("FARM_RECORD", "EQUIPMENT_TELEMETRY", "REMOTE_SENSING", "ATTESTATION")

FIELD_FILTERS = {
    "grower_id": ("grower_id", "str"),
    "status": ("status", "str"),
    "soil_group": ("soil_group", "str"),
    "county_code": ("county_code", "str"),
}

HISTORY_FILTERS = {
    "field_id": ("field_id", "str"),
    "crop_year": ("crop_year", "int"),
    "practice_code": ("practice_code", "str"),
    "evidence_source": ("evidence_source", "str"),
}


@bp.route("/growers/<grower_id>/fields", methods=["POST"])
def create_field(grower_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN, mw.ROLE_GROWER)
    grower = common.get_grower(grower_id)
    mw.require_grower_owner(grower["id"])
    body = v.json_body()

    field_name = v.v_str(body, "field_name")
    min_x = v.v_int(body, "boundary_min_x", minimum=0)
    min_y = v.v_int(body, "boundary_min_y", minimum=0)
    max_x = v.v_int(body, "boundary_max_x")
    max_y = v.v_int(body, "boundary_max_y")
    if max_x <= min_x:
        v.bad("Field 'boundary_max_x' must be strictly greater than 'boundary_min_x'.")
    if max_y <= min_y:
        v.bad("Field 'boundary_max_y' must be strictly greater than 'boundary_min_y'.")
    gross_acres = v.v_dec(body, "gross_acres", 2, minimum=0, exclusive_min=True)
    soil_group = v.v_enum(body, "soil_group", SOIL_GROUPS)
    county_code = v.v_str(body, "county_code", required=False)

    if grower["status"] == "SUSPENDED":
        common.fail("ERR_GROWER_SUSPENDED")

    candidate = {
        "boundary_min_x": min_x,
        "boundary_min_y": min_y,
        "boundary_max_x": max_x,
        "boundary_max_y": max_y,
    }
    for other in db.sorted_rows(db.fields):
        if other["grower_id"] != grower["id"] or other["status"] == "SUSPENDED":
            continue
        if calc.rectangles_overlap(candidate, other):
            common.fail("ERR_FIELD_BOUNDARY_OVERLAP")

    row = db.common_fields()
    row.update(candidate)
    row.update({
        "grower_id": grower["id"],
        "field_name": field_name,
        "gross_acres": gross_acres,
        "mapped_acres": calc.mapped_acres(min_x, min_y, max_x, max_y),
        "soil_group": soil_group,
        "county_code": county_code,
        "status": "DRAFT",
        "surveyor_reference": None,
    })
    db.fields[row["id"]] = row
    return resp.object_response(serialize.field(row), 201)


@bp.route("/fields", methods=["GET"])
def list_fields():
    mw.authorize(mw.ROLE_PROGRAM_ADMIN, mw.ROLE_GROWER, mw.ROLE_REGISTRY_OFFICER)
    rows = common.apply_filters(db.fields.values(), FIELD_FILTERS)
    return resp.paginate(rows, serialize.field)


@bp.route("/fields/<field_id>", methods=["GET"])
def read_field(field_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN, mw.ROLE_GROWER, mw.ROLE_REGISTRY_OFFICER)
    row = common.get_field(field_id)
    mw.require_grower_owner(row["grower_id"])
    return resp.object_response(serialize.field(row))


@bp.route("/fields/<field_id>/map-confirm", methods=["POST"])
def map_confirm(field_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN)
    field = common.get_field(field_id)
    body = v.json_body()
    surveyor_reference = v.v_str(body, "surveyor_reference")
    grower = db.growers.get(field["grower_id"])
    if grower is not None and grower["status"] == "SUSPENDED":
        common.fail("ERR_GROWER_SUSPENDED")
    if field["status"] != "DRAFT":
        common.fail("ERR_INVALID_STATE_TRANSITION", "Only a DRAFT field may be survey-confirmed.")
    field["surveyor_reference"] = surveyor_reference
    field["status"] = "MAPPED"
    db.touch(field)
    return resp.object_response(serialize.field(field))


@bp.route("/fields/<field_id>/practice-history", methods=["POST"])
def create_practice_history(field_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN, mw.ROLE_GROWER)
    field = common.get_field(field_id)
    mw.require_grower_owner(field["grower_id"])
    body = v.json_body()

    crop_year = v.v_crop_year(body, "crop_year")
    practice_code = v.v_enum(body, "practice_code", PRACTICE_CODES)
    adopted = v.v_bool(body, "adopted")
    evidence_source = v.v_enum(body, "evidence_source", EVIDENCE_SOURCES)
    acres = v.v_dec(body, "acres", 2, minimum=0)
    observed = v.v_dec(body, "observed_emissions_per_acre", 4, required=False, minimum=0)

    grower = db.growers.get(field["grower_id"])
    if grower is not None and grower["status"] == "SUSPENDED":
        common.fail("ERR_GROWER_SUSPENDED")

    row = {
        "id": db.new_id(),
        "created_at": db.now_ts(),
        "_seq": db.next_seq(),
        "field_id": field["id"],
        "crop_year": crop_year,
        "practice_code": practice_code,
        "adopted": adopted,
        "evidence_source": evidence_source,
        "acres": acres,
        "observed_emissions_per_acre": observed if observed is not None else Decimal("0.0000"),
    }
    db.practice_history[row["id"]] = row
    return resp.object_response(serialize.practice_history(row), 201)


@bp.route("/practice-history", methods=["GET"])
def list_practice_history():
    mw.authorize(mw.ROLE_PROGRAM_ADMIN, mw.ROLE_GROWER, mw.ROLE_VERIFIER)
    rows = common.apply_filters(db.practice_history.values(), HISTORY_FILTERS)
    return resp.paginate(rows, serialize.practice_history)


@bp.route("/practice-history/<practice_history_id>", methods=["GET"])
def read_practice_history(practice_history_id):
    mw.authorize(mw.ROLE_PROGRAM_ADMIN, mw.ROLE_GROWER, mw.ROLE_VERIFIER)
    row = common.get_practice_history(practice_history_id)
    field = db.fields.get(row["field_id"])
    if field is not None:
        mw.require_grower_owner(field["grower_id"])
    return resp.object_response(serialize.practice_history(row))
