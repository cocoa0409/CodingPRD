"""Play areas and component placements (PRD sections 3.2, 3.3 and 3.9 retrofits)."""

from flask import Blueprint

import calc
import validate as v
from auth import READ_ROLES, authenticate
from envelope import list_response, no_content_response, object_response
from errors import ApiError
from routes_projects import require_editable
from store import public, public_list, store

bp = Blueprint("areas", __name__)

RETROFIT_ROLES = ["ClientRepresentative", "DesignConsultant"]

ATTACHMENT_PARENT_CATEGORY = {
    "PLASTIC_SLIDE": "DECK",
    "METAL_CLIMBER": "DECK",
    "DECK": "POST",
}


def require_unlocked(area):
    if area["status"] == "LOCKED":
        raise ApiError("ERR_PLAY_AREA_LOCKED")


@bp.route("/playground/play-areas/<area_id>", methods=["GET"])
def get_play_area(area_id):
    authenticate(READ_ROLES)
    return object_response(public(store.require("area", area_id)))


# ------------------------------------------------------------------ placements

@bp.route("/playground/play-areas/<area_id>/placements", methods=["POST"])
def create_placement(area_id):
    authenticate(["DesignConsultant"])
    area = store.require("area", area_id)
    project = store.get("project", area["project_id"])
    body = v.raw_body()
    resolved = v.resolve_fks(body, [
        ("component_model_id", "model", True),
        ("attached_to_placement_id", "placement", False),
    ])
    v.string(body, "component_model_id", min_len=1)
    model = resolved["component_model_id"]
    parent = resolved.get("attached_to_placement_id")
    color = v.string(body, "color_choice", min_len=1)
    x_start = v.integer(body, "x_start_cm", minimum=0)
    quantity = v.integer(body, "quantity", minimum=1, maximum=50)
    if color not in model["color_options"]:
        raise v.bad_request("color_choice must be one of the model's color_options.")

    require_editable(project)
    require_unlocked(area)

    if model["certification_status"] != "CERTIFIED":
        raise ApiError("ERR_MODEL_NOT_CERTIFIED")
    if model["lifecycle_status"] == "DISCONTINUED":
        raise ApiError("ERR_MODEL_DISCONTINUED")

    standard = store.active_standard()
    if standard is None:
        raise ApiError("ERR_NO_ACTIVE_STANDARD")

    ceiling = standard[calc.FALL_HEIGHT_FIELD[area["age_group"]]]
    if model["deck_height_cm"] > ceiling:
        raise ApiError("ERR_FALL_HEIGHT_EXCEEDS_STANDARD")
    prospective = max(calc.area_critical_fall_height(area), model["deck_height_cm"])
    if prospective > calc.MAX_CRITICAL_FALL_HEIGHT_CM:
        raise ApiError("ERR_FALL_HEIGHT_EXCEEDS_STANDARD")
    if model["age_group"] != area["age_group"]:
        raise ApiError("ERR_AGE_GROUP_MISMATCH")

    zone_start, zone_end = calc.use_zone_extent(model, x_start)
    if zone_start < area["axis_origin_cm"]:
        raise ApiError("ERR_USE_ZONE_OUT_OF_BOUNDS")
    if zone_end >= area["axis_origin_cm"] + area["axis_length_cm"]:
        raise ApiError("ERR_USE_ZONE_OUT_OF_BOUNDS")

    expected_parent_category = ATTACHMENT_PARENT_CATEGORY.get(model["category"])
    if parent is None:
        if "attached_to_placement_id" in body and body["attached_to_placement_id"] is not None:
            raise ApiError("ERR_INVALID_ATTACHMENT_TARGET")
    else:
        if expected_parent_category is None:
            raise ApiError("ERR_INVALID_ATTACHMENT_TARGET")
        if parent["play_area_id"] != area_id:
            raise ApiError("ERR_INVALID_ATTACHMENT_TARGET")
        parent_model = store.get("model", parent["component_model_id"])
        if parent_model is None or parent_model["category"] != expected_parent_category:
            raise ApiError("ERR_INVALID_ATTACHMENT_TARGET")

    row = store.insert("placement", {
        "play_area_id": area_id,
        "component_model_id": model["id"],
        "attached_to_placement_id": parent["id"] if parent else None,
        "color_choice": color,
        "x_start_cm": x_start,
        "quantity": quantity,
        "use_zone_start_cm": zone_start,
        "use_zone_end_cm": zone_end,
        "status": "DRAFT",
        "retrofit_model_id": None,
        "retrofit_quantity": 0,
        "retrofit_unit_price_cents": 0,
        "retrofit_handling_cents": 0,
        "retrofit_total_cents": 0,
        "legacy_surcharge_applied": False,
    })

    before = (area["critical_fall_height_cm"], area["required_surfacing_depth_cm"])
    calc.recompute_area_geometry_quiet(area)
    if (area["critical_fall_height_cm"], area["required_surfacing_depth_cm"]) != before:
        store.touch(area)
    return object_response(public(row), 201)


@bp.route("/playground/play-areas/<area_id>/placements", methods=["GET"])
def list_area_placements(area_id):
    authenticate(READ_ROLES)
    store.require("area", area_id)
    limit, offset = v.pagination()
    rows = v.apply_filters(store.area_placements(area_id), {"status": "status"})
    page, total = v.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


@bp.route("/playground/placements", methods=["GET"])
def list_placements():
    authenticate(READ_ROLES)
    limit, offset = v.pagination()
    rows = v.apply_filters(store.all("placement"), {
        "play_area_id": "play_area_id",
        "component_model_id": "component_model_id",
        "attached_to_placement_id": "attached_to_placement_id",
        "retrofit_model_id": "retrofit_model_id",
        "status": "status",
    })
    page, total = v.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


@bp.route("/playground/placements/<placement_id>", methods=["GET"])
def get_placement(placement_id):
    authenticate(READ_ROLES)
    return object_response(public(store.require("placement", placement_id)))


@bp.route("/playground/placements/<placement_id>/validate", methods=["POST"])
def validate_placement(placement_id):
    authenticate(["DesignConsultant"])
    placement = store.require("placement", placement_id)
    area = store.get("area", placement["play_area_id"])
    project = store.get("project", area["project_id"])

    if placement["status"] != "DRAFT":
        raise ApiError("ERR_PLACEMENT_INVALID_STATE")
    require_editable(project)
    require_unlocked(area)

    model = store.get("model", placement["component_model_id"])
    if model["certification_status"] != "CERTIFIED":
        raise ApiError("ERR_MODEL_NOT_CERTIFIED")

    if placement["attached_to_placement_id"] is not None:
        parent = store.get("placement", placement["attached_to_placement_id"])
        if parent is None or parent["status"] != "VALIDATED":
            raise ApiError("ERR_PARENT_PLACEMENT_NOT_VALIDATED")

    standard = store.active_standard()
    if standard is not None:
        clearance = standard["min_use_zone_clearance_cm"]
        for other in store.project_placements(project["id"]):
            if other["id"] == placement_id or other["status"] != "VALIDATED":
                continue
            if other["play_area_id"] == placement["play_area_id"]:
                continue
            gap = calc.clear_separation(
                placement["use_zone_start_cm"], placement["use_zone_end_cm"],
                other["use_zone_start_cm"], other["use_zone_end_cm"],
            )
            if gap < clearance:
                raise ApiError("ERR_AGE_GROUP_SEPARATION_VIOLATION")

    for other in store.area_placements(placement["play_area_id"]):
        if other["id"] == placement_id or other["status"] != "VALIDATED":
            continue
        if placement["attached_to_placement_id"] == other["id"]:
            continue
        if other["attached_to_placement_id"] == placement_id:
            continue
        if calc.zones_overlap(
            placement["use_zone_start_cm"], placement["use_zone_end_cm"],
            other["use_zone_start_cm"], other["use_zone_end_cm"],
        ):
            raise ApiError("ERR_USE_ZONE_OVERLAP")

    placement["status"] = "VALIDATED"
    store.touch(placement)
    if area["status"] == "PLANNED":
        area["status"] = "ZONED"
    calc.recompute_area_geometry_quiet(area)
    store.touch(area)
    return object_response(public(placement))


@bp.route("/playground/placements/<placement_id>", methods=["DELETE"])
def delete_placement(placement_id):
    authenticate(["DesignConsultant"])
    placement = store.require("placement", placement_id)
    area = store.get("area", placement["play_area_id"])
    project = store.get("project", area["project_id"])
    require_editable(project)
    require_unlocked(area)

    for child in store.all("placement"):
        if child["attached_to_placement_id"] == placement_id:
            child["attached_to_placement_id"] = None
            store.touch(child)

    store.delete("placement", placement_id)
    calc.recompute_area_geometry_quiet(area)
    store.touch(area)
    return no_content_response()


# -------------------------------------------------- replacement parts/retrofit

@bp.route("/playground/placements/<placement_id>/retrofit", methods=["POST"])
def retrofit_placement(placement_id):
    authenticate(RETROFIT_ROLES)
    placement = store.require("placement", placement_id)
    area = store.get("area", placement["play_area_id"])
    project = store.get("project", area["project_id"])
    body = v.raw_body()
    resolved = v.resolve_fks(body, [("replacement_model_id", "model", True)])
    v.string(body, "replacement_model_id", min_len=1)
    replacement = resolved["replacement_model_id"]
    quantity = v.integer(body, "quantity", minimum=1)

    recert = placement["status"] == "NEEDS_RECERTIFICATION"
    current_model_id = placement["component_model_id"]
    supersedes_current = replacement["supersedes_model_id"] == current_model_id

    if recert:
        if replacement["certification_status"] != "CERTIFIED":
            raise ApiError("ERR_MODEL_NOT_CERTIFIED")
        standard = store.active_standard()
        if standard is not None:
            ceiling = standard[calc.FALL_HEIGHT_FIELD[area["age_group"]]]
            if replacement["deck_height_cm"] > ceiling:
                raise ApiError("ERR_FALL_HEIGHT_EXCEEDS_STANDARD")
        if replacement["age_group"] != area["age_group"]:
            raise ApiError("ERR_AGE_GROUP_MISMATCH")

    if store.clock.year() > replacement["parts_support_until_year"]:
        raise ApiError("ERR_PARTS_NO_LONGER_AVAILABLE")

    if recert:
        if not supersedes_current:
            raise ApiError("ERR_RETROFIT_MODEL_MISMATCH")
    else:
        if replacement["id"] != current_model_id and not supersedes_current:
            raise ApiError("ERR_RETROFIT_MODEL_MISMATCH")

    pricing = calc.replacement_retrofit_pricing(replacement, quantity)
    placement["retrofit_model_id"] = replacement["id"]
    placement["retrofit_quantity"] = quantity
    placement["retrofit_unit_price_cents"] = pricing["retrofit_unit_price_cents"]
    placement["retrofit_handling_cents"] = pricing["retrofit_handling_cents"]
    placement["retrofit_total_cents"] = pricing["retrofit_total_cents"]
    placement["legacy_surcharge_applied"] = pricing["legacy_surcharge_applied"]

    if recert and supersedes_current:
        placement["component_model_id"] = replacement["id"]
        placement["status"] = "VALIDATED"
    store.touch(placement)

    calc.recompute_area_geometry_quiet(area)
    store.touch(area)

    remaining = [p for p in store.project_placements(project["id"])
                 if p["status"] == "NEEDS_RECERTIFICATION"]
    if not remaining and project["compliance_status"] == "RETROFIT_REQUIRED":
        project["compliance_status"] = "COMPLIANT"
    store.touch(project)

    return object_response(public(placement))
