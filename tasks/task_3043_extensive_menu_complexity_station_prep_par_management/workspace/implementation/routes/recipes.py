from flask import Blueprint, request

from db import db, new_id
from middleware import get_user_context, require_roles, get_json_body, ALL_ROLES
from response import success_object, success_array
from services.common import (
    new_entity, require_fields, check_str, check_enum, check_array,
    resolve, list_paginated, STATION_TYPES, MODIFICATION_POLICIES,
)
from errors import ApiError, err_invalid_request

bp = Blueprint("recipes", __name__)


def serialize(r):
    return {
        "id": r["id"],
        "menu_revision_id": r["menu_revision_id"],
        "name": r["name"],
        "station_type": r["station_type"],
        "allergen_tags": r["allergen_tags"],
        "modification_policy": r["modification_policy"],
        "components": r["components"],
        "status": r["status"],
        "created_at": r["created_at"],
        "updated_at": r["updated_at"],
        "version": r["version"],
    }


@bp.route("/api/recipes", methods=["POST"])
def create_recipe():
    get_user_context()
    body = get_json_body()
    require_fields(body, ["menu_revision_id", "name", "station_type"])
    mrid = check_str(body, "menu_revision_id")
    name = check_str(body, "name")
    stype = check_enum(body, "station_type", STATION_TYPES)
    allergen_tags = check_array(body, "allergen_tags", required=False, default=[])
    policy = check_enum(body, "modification_policy", MODIFICATION_POLICIES, required=False, default="ALLOWED")
    components = check_array(body, "components", required=False, default=[])
    comps = []
    for c in components:
        if not isinstance(c, dict):
            raise err_invalid_request("Each component must be an object")
        pid = c.get("prep_item_id")
        qpp = c.get("quantity_per_portion")
        unit = c.get("unit")
        if not isinstance(pid, str):
            raise err_invalid_request("component.prep_item_id must be a string")
        if isinstance(qpp, bool) or not isinstance(qpp, int) or qpp < 0:
            raise err_invalid_request("component.quantity_per_portion must be a non-negative integer")
        if not isinstance(unit, str):
            raise err_invalid_request("component.unit must be a string")
        comps.append({"prep_item_id": pid, "quantity_per_portion": qpp, "unit": unit})
    require_roles("MenuAdmin")
    rev = resolve("menu_revision", mrid)
    for c in comps:
        resolve("prep_item", c["prep_item_id"])
    if rev["status"] not in ("DRAFT", "IN_REVIEW"):
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Recipe may only be created while revision is DRAFT or IN_REVIEW")
    for c in comps:
        item = db.prep_items[c["prep_item_id"]]
        if item["status"] != "ACTIVE":
            raise ApiError("ERR_PREP_ITEM_NOT_ACTIVE", 422, "Component references a RETIRED prep item")
    ent = {
        "id": new_id(),
        "menu_revision_id": mrid,
        "name": name,
        "station_type": stype,
        "allergen_tags": allergen_tags,
        "modification_policy": policy,
        "components": comps,
        "status": "DRAFT",
        "_seq": db.next_seq(),
        **new_entity(),
    }
    db.recipes[ent["id"]] = ent
    return success_object(serialize(ent), status=201)


@bp.route("/api/recipes", methods=["GET"])
def list_recipes():
    require_roles(*ALL_ROLES)
    page, limit, offset, total = list_paginated(
        db.recipes,
        [("menu_revision_id", "menu_revision_id"), ("status", "status"), ("station_type", "station_type")],
        request.args,
    )
    return success_array([serialize(r) for r in page], limit, offset, total)


@bp.route("/api/recipes/<rid>", methods=["GET"])
def get_recipe(rid):
    require_roles(*ALL_ROLES)
    r = resolve("recipe", rid)
    return success_object(serialize(r))
