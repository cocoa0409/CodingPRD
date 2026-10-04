from flask import Blueprint, request

from db import db, new_id
from middleware import get_user_context, require_roles, get_json_body, ALL_ROLES
from response import success_object, success_array
from services.common import (
    new_entity, require_fields, check_str, check_enum, check_int,
    resolve, list_paginated, STATION_TYPES, BATCH_UNITS, retire_prep_item,
)
from errors import ApiError

bp = Blueprint("prep_items", __name__)


def serialize(p):
    return {
        "id": p["id"],
        "name": p["name"],
        "station_type": p["station_type"],
        "shelf_life_hours": p["shelf_life_hours"],
        "min_batch_size": p["min_batch_size"],
        "batch_unit": p["batch_unit"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


@bp.route("/api/prep-items", methods=["POST"])
def create_prep_item():
    get_user_context()
    body = get_json_body()
    require_fields(body, ["name", "station_type", "shelf_life_hours", "min_batch_size", "batch_unit"])
    name = check_str(body, "name")
    stype = check_enum(body, "station_type", STATION_TYPES)
    shelf = check_int(body, "shelf_life_hours", min_value=1)
    mbs = check_int(body, "min_batch_size", min_value=1)
    unit = check_enum(body, "batch_unit", BATCH_UNITS)
    require_roles("MenuAdmin")
    ent = {
        "id": new_id(),
        "name": name,
        "station_type": stype,
        "shelf_life_hours": shelf,
        "min_batch_size": mbs,
        "batch_unit": unit,
        "status": "ACTIVE",
        "_seq": db.next_seq(),
        **new_entity(),
    }
    db.prep_items[ent["id"]] = ent
    return success_object(serialize(ent), status=201)


@bp.route("/api/prep-items", methods=["GET"])
def list_prep_items():
    require_roles(*ALL_ROLES)
    page, limit, offset, total = list_paginated(
        db.prep_items,
        [("status", "status"), ("station_type", "station_type")],
        request.args,
    )
    return success_array([serialize(p) for p in page], limit, offset, total)


@bp.route("/api/prep-items/<pid>", methods=["GET"])
def get_prep_item(pid):
    require_roles(*ALL_ROLES)
    p = resolve("prep_item", pid)
    return success_object(serialize(p))


@bp.route("/api/prep-items/<pid>/retire", methods=["POST"])
def retire(pid):
    get_user_context()
    get_json_body()
    require_roles("MenuAdmin")
    p = resolve("prep_item", pid)
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Item must be ACTIVE to retire")
    retire_prep_item(p)
    return success_object(serialize(p))
