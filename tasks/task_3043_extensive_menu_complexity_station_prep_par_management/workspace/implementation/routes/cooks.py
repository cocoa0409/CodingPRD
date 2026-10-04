from flask import Blueprint, request

from db import db, new_id
from middleware import get_user_context, require_roles, get_json_body, ALL_ROLES
from response import success_object, success_array
from services.common import (
    new_entity, touch, require_fields, check_str, check_array,
    resolve, list_paginated,
)
from errors import ApiError

bp = Blueprint("cooks", __name__)


def serialize(c):
    return {
        "id": c["id"],
        "restaurant_id": c["restaurant_id"],
        "name": c["name"],
        "certified_station_types": c["certified_station_types"],
        "certification_menu_revision_id": c["certification_menu_revision_id"],
        "weekly_scheduled_minutes": c["weekly_scheduled_minutes"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.route("/api/cooks", methods=["POST"])
def create_cook():
    get_user_context()
    body = get_json_body()
    require_fields(body, ["restaurant_id", "name", "certified_station_types"])
    rid = check_str(body, "restaurant_id")
    name = check_str(body, "name")
    certs = check_array(body, "certified_station_types")
    require_roles("KitchenManager")
    resolve("restaurant", rid)
    ent = {
        "id": new_id(),
        "restaurant_id": rid,
        "name": name,
        "certified_station_types": certs,
        "certification_menu_revision_id": None,
        "weekly_scheduled_minutes": 0,
        "status": "ACTIVE",
        "_seq": db.next_seq(),
        **new_entity(),
    }
    db.cooks[ent["id"]] = ent
    return success_object(serialize(ent), status=201)


@bp.route("/api/cooks", methods=["GET"])
def list_cooks():
    require_roles(*ALL_ROLES)
    page, limit, offset, total = list_paginated(
        db.cooks,
        [("restaurant_id", "restaurant_id"), ("status", "status")],
        request.args,
    )
    return success_array([serialize(c) for c in page], limit, offset, total)


@bp.route("/api/cooks/<cid>", methods=["GET"])
def get_cook(cid):
    require_roles(*ALL_ROLES)
    c = resolve("cook", cid)
    return success_object(serialize(c))


@bp.route("/api/cooks/<cid>/complete-retraining", methods=["POST"])
def complete_retraining(cid):
    get_user_context()
    body = get_json_body()
    require_fields(body, ["menu_revision_id"])
    mrid = body["menu_revision_id"]
    require_roles("KitchenManager")
    cook = resolve("cook", cid)
    rev = resolve("menu_revision", mrid)
    if cook["status"] != "RETRAINING_REQUIRED":
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Cook must be RETRAINING_REQUIRED")
    published = [
        r for r in db.menu_revisions.values()
        if r["restaurant_id"] == cook["restaurant_id"] and r["status"] == "PUBLISHED"
    ]
    published.sort(key=lambda r: (r["created_at"], r.get("_seq", 0)))
    latest = published[-1] if published else None
    if latest is None or rev["id"] != latest["id"]:
        raise ApiError("ERR_MENU_REVISION_NOT_PUBLISHED", 409, "menu_revision_id must be the restaurant's latest PUBLISHED revision")
    cook["certification_menu_revision_id"] = mrid
    cook["status"] = "ACTIVE"
    touch(cook)
    return success_object(serialize(cook))
