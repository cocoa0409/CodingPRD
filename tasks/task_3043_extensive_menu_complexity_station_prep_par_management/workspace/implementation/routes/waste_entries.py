from flask import Blueprint, request

from db import db, new_id
from middleware import get_user_context, require_roles, get_json_body, ALL_ROLES
from response import success_object, success_array
from services.common import (
    new_entity, touch, require_fields, check_int, check_enum,
    resolve, list_paginated, recompute_par_health, finalize_batch_terminal,
    WASTE_REASONS,
)
from errors import ApiError

bp = Blueprint("waste_entries", __name__)


def serialize(w):
    return {
        "id": w["id"],
        "station_id": w["station_id"],
        "prep_batch_id": w["prep_batch_id"],
        "quantity": w["quantity"],
        "reason": w["reason"],
        "recorded_by_cook_id": w["recorded_by_cook_id"],
        "status": w["status"],
        "created_at": w["created_at"],
        "updated_at": w["updated_at"],
        "version": w["version"],
    }


@bp.route("/api/waste-entries", methods=["POST"])
def create_waste_entry():
    uid, role = get_user_context()
    body = get_json_body()
    require_fields(body, ["station_id", "prep_batch_id", "quantity", "reason"])
    sid = body["station_id"]
    bid = body["prep_batch_id"]
    qty = check_int(body, "quantity", min_value=1)
    reason = check_enum(body, "reason", WASTE_REASONS)
    require_roles("LineCook", "PrepCook", "PastryChef")
    resolve("station", sid)
    batch = resolve("prep_batch", bid)
    remaining = batch["quantity"] - batch["consumed_quantity"] - batch["wasted_quantity"]
    if qty > remaining:
        raise ApiError("ERR_INVALID_REQUEST", 400, "quantity may not exceed the batch's remaining quantity")
    ent = {
        "id": new_id(),
        "station_id": sid,
        "prep_batch_id": bid,
        "quantity": qty,
        "reason": reason,
        "recorded_by_cook_id": uid,
        "status": "RECORDED",
        "_seq": db.next_seq(),
        **new_entity(),
    }
    db.waste_entries[ent["id"]] = ent
    batch["wasted_quantity"] += qty
    touch(batch)
    if batch["consumed_quantity"] + batch["wasted_quantity"] >= batch["quantity"] and batch["status"] == "PREPPED":
        finalize_batch_terminal(batch, "WASTED")
    else:
        recompute_par_health(sid)
    return success_object(serialize(ent), status=201)


@bp.route("/api/waste-entries", methods=["GET"])
def list_waste_entries():
    require_roles(*ALL_ROLES)
    page, limit, offset, total = list_paginated(
        db.waste_entries,
        [
            ("station_id", "station_id"),
            ("prep_batch_id", "prep_batch_id"),
            ("recorded_by_cook_id", "recorded_by_cook_id"),
            ("reason", "reason"),
        ],
        request.args,
    )
    return success_array([serialize(w) for w in page], limit, offset, total)


@bp.route("/api/waste-entries/<wid>", methods=["GET"])
def get_waste_entry(wid):
    require_roles(*ALL_ROLES)
    w = resolve("waste_entry", wid)
    return success_object(serialize(w))
