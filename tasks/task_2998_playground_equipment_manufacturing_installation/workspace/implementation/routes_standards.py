"""Safety standard editions and the component catalogue (PRD section 3.1)."""

from flask import Blueprint

import calc
import cascades
import validate as v
from auth import READ_ROLES, authenticate
from envelope import list_response, object_response
from errors import ApiError
from store import parse_date, public, public_list, store

bp = Blueprint("standards", __name__)

CODE_PATTERN = r"^[A-Z0-9_]+$"
LIFECYCLE_STATUSES = ("ACTIVE", "LEGACY", "DISCONTINUED")
LIFECYCLE_TRANSITIONS = {("ACTIVE", "LEGACY"), ("LEGACY", "DISCONTINUED")}


# ------------------------------------------------------------------- standards

@bp.route("/playground/standards", methods=["POST"])
def create_standard():
    authenticate(["ManufacturerAdmin", "ComplianceOfficer"])
    body = v.raw_body()
    code = v.string(body, "code", min_len=1, max_len=40, pattern=CODE_PATTERN,
                    pattern_hint="uppercase letters, digits and underscore")
    edition_year = v.integer(body, "edition_year", minimum=2000, maximum=2100)
    effective_from = v.date_field(body, "effective_from")
    clearance = v.integer(body, "min_use_zone_clearance_cm", minimum=0)
    toddler = v.integer(body, "max_fall_height_cm_toddler", minimum=1)
    preschool = v.integer(body, "max_fall_height_cm_preschool", minimum=1)
    school_age = v.integer(body, "max_fall_height_cm_school_age", minimum=1)
    accessible = v.boolean(body, "requires_accessible_route", default=True)

    for row in store.all("standard"):
        if row["code"] == code and row["edition_year"] == edition_year:
            raise v.bad_request(
                "Edition year {} of standard '{}' is already registered.".format(edition_year, code)
            )

    row = store.insert("standard", {
        "code": code,
        "edition_year": edition_year,
        "effective_from": effective_from.isoformat(),
        "min_use_zone_clearance_cm": clearance,
        "max_fall_height_cm_toddler": toddler,
        "max_fall_height_cm_preschool": preschool,
        "max_fall_height_cm_school_age": school_age,
        "requires_accessible_route": accessible,
        "status": "DRAFT",
        "superseded_by_standard_id": None,
    })
    return object_response(public(row), 201)


@bp.route("/playground/standards", methods=["GET"])
def list_standards():
    authenticate(READ_ROLES)
    limit, offset = v.pagination()
    rows = v.apply_filters(store.all("standard"), {
        "status": "status",
        "code": "code",
        "superseded_by_standard_id": "superseded_by_standard_id",
    })
    page, total = v.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


@bp.route("/playground/standards/<standard_id>", methods=["GET"])
def get_standard(standard_id):
    authenticate(READ_ROLES)
    return object_response(public(store.require("standard", standard_id)))


@bp.route("/playground/standards/<standard_id>/activate", methods=["POST"])
def activate_standard(standard_id):
    authenticate(["ComplianceOfficer"])
    row = store.require("standard", standard_id)
    if row["status"] != "DRAFT":
        raise ApiError("ERR_STANDARD_NOT_DRAFT")
    if store.active_standard() is not None:
        raise ApiError("ERR_ACTIVE_STANDARD_EXISTS")
    row["status"] = "ACTIVE"
    store.touch(row)
    return object_response(public(row))


@bp.route("/playground/standards/<standard_id>/supersede", methods=["POST"])
def supersede_standard(standard_id):
    authenticate(["ComplianceOfficer"])
    row = store.require("standard", standard_id)
    body = v.raw_body()
    resolved = v.resolve_fks(body, [("successor_standard_id", "standard", True)])
    v.string(body, "successor_standard_id", min_len=1)
    successor = resolved["successor_standard_id"]

    if row["status"] != "ACTIVE":
        raise ApiError("ERR_STANDARD_NOT_ACTIVE")
    if successor["status"] != "DRAFT":
        raise ApiError("ERR_SUCCESSOR_NOT_DRAFT")
    if parse_date(successor["effective_from"]) > store.clock.today():
        raise ApiError("ERR_SUCCESSOR_NOT_EFFECTIVE")

    cascades.supersede_standard(row, successor)
    return object_response(public(row))


# ------------------------------------------------------------ component models

@bp.route("/playground/component-models", methods=["POST"])
def create_model():
    authenticate(["ManufacturerAdmin"])
    body = v.raw_body()
    resolved = v.resolve_fks(body, [("supersedes_model_id", "model", False)])
    sku = v.string(body, "sku", min_len=1, max_len=40)
    category = v.enum(body, "category", calc.CATEGORIES)
    age_group = v.enum(body, "age_group", calc.AGE_GROUPS)
    deck_height = v.integer(body, "deck_height_cm", minimum=0, maximum=400)
    footprint = v.integer(body, "use_zone_footprint_cm", minimum=0)
    colors = v.color_options(body, "color_options")
    unit_price = v.integer(body, "unit_price_cents", minimum=1)
    bags = v.integer(body, "hardware_bag_count", minimum=0)
    warranty_years = v.integer(body, "warranty_years", minimum=1, maximum=50)
    parts_year = v.integer(body, "parts_support_until_year", minimum=2000, maximum=2200)
    accessible = v.boolean(body, "accessible_transfer_ready", default=False)
    supersedes = resolved.get("supersedes_model_id")

    for row in store.all("model"):
        if row["sku"] == sku:
            raise v.bad_request("SKU '{}' is already in the catalogue.".format(sku))

    row = store.insert("model", {
        "sku": sku,
        "category": category,
        "age_group": age_group,
        "deck_height_cm": deck_height,
        "use_zone_footprint_cm": footprint,
        "color_options": colors,
        "unit_price_cents": unit_price,
        "hardware_bag_count": bags,
        "warranty_years": warranty_years,
        "parts_support_until_year": parts_year,
        "accessible_transfer_ready": accessible,
        "supersedes_model_id": supersedes["id"] if supersedes else None,
        "certification_status": "UNCERTIFIED",
        "certified_against_standard_id": None,
        "lifecycle_status": "ACTIVE",
    })
    return object_response(public(row), 201)


@bp.route("/playground/component-models", methods=["GET"])
def list_models():
    authenticate(READ_ROLES)
    limit, offset = v.pagination()
    rows = v.apply_filters(store.all("model"), {
        "category": "category",
        "age_group": "age_group",
        "certification_status": "certification_status",
        "lifecycle_status": "lifecycle_status",
        "supersedes_model_id": "supersedes_model_id",
        "certified_against_standard_id": "certified_against_standard_id",
    })
    page, total = v.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


@bp.route("/playground/component-models/<model_id>", methods=["GET"])
def get_model(model_id):
    authenticate(READ_ROLES)
    return object_response(public(store.require("model", model_id)))


@bp.route("/playground/component-models/<model_id>/certify", methods=["POST"])
def certify_model(model_id):
    authenticate(["ComplianceOfficer"])
    model = store.require("model", model_id)
    if model["certification_status"] not in ("UNCERTIFIED", "DECERTIFIED"):
        raise ApiError("ERR_MODEL_NOT_CERTIFIABLE")
    if model["lifecycle_status"] == "DISCONTINUED":
        raise ApiError("ERR_MODEL_NOT_CERTIFIABLE")
    standard = store.active_standard()
    if standard is None:
        raise ApiError("ERR_NO_ACTIVE_STANDARD")
    ceiling = standard[calc.FALL_HEIGHT_FIELD[model["age_group"]]]
    if model["deck_height_cm"] > ceiling:
        raise ApiError("ERR_FALL_HEIGHT_EXCEEDS_STANDARD")
    model["certification_status"] = "CERTIFIED"
    model["certified_against_standard_id"] = standard["id"]
    store.touch(model)
    return object_response(public(model))


@bp.route("/playground/component-models/<model_id>/lifecycle", methods=["POST"])
def move_model_lifecycle(model_id):
    authenticate(["ManufacturerAdmin"])
    model = store.require("model", model_id)
    body = v.raw_body()
    target = v.enum(body, "lifecycle_status", LIFECYCLE_STATUSES)
    if (model["lifecycle_status"], target) not in LIFECYCLE_TRANSITIONS:
        raise ApiError("ERR_MODEL_NOT_CERTIFIABLE")
    model["lifecycle_status"] = target
    store.touch(model)
    return object_response(public(model))
