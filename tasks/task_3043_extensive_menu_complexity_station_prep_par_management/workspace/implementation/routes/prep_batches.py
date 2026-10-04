from datetime import timedelta

from flask import Blueprint, request

from db import db, new_id, clock_now, format_iso
from middleware import get_user_context, require_roles, get_json_body, ALL_ROLES
from response import success_object, success_array
from services.common import (
    new_entity, touch, require_fields, check_int, resolve, list_paginated,
    rack_load, recompute_par_health, finalize_batch_terminal,
)
from errors import ApiError

bp = Blueprint("prep_batches", __name__)


def serialize(b):
    return {
        "id": b["id"],
        "prep_list_id": b["prep_list_id"],
        "prep_item_id": b["prep_item_id"],
        "station_id": b["station_id"],
        "quantity": b["quantity"],
        "consumed_quantity": b["consumed_quantity"],
        "wasted_quantity": b["wasted_quantity"],
        "produced_at": b["produced_at"],
        "expires_at": b["expires_at"],
        "status": b["status"],
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


@bp.route("/api/prep-batches", methods=["POST"])
def create_batch():
    get_user_context()
    body = get_json_body()
    require_fields(body, ["prep_list_id", "prep_item_id", "station_id", "quantity"])
    plid = body["prep_list_id"]
    pid = body["prep_item_id"]
    sid = body["station_id"]
    qty = check_int(body, "quantity", min_value=1)
    require_roles("PrepCook", "KitchenManager")
    pl = resolve("prep_list", plid)
    item = resolve("prep_item", pid)
    station = resolve("station", sid)
    if qty % item["min_batch_size"] != 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "quantity must be a multiple of min_batch_size")
    if pl["status"] not in ("LOCKED", "IN_PROGRESS"):
        raise ApiError("ERR_PREP_LIST_NOT_LOCKED", 409, "batch creation requires LOCKED or IN_PROGRESS prep list")
    if rack_load(sid) + qty > station["rack_slot_capacity"]:
        raise ApiError("ERR_RACK_CAPACITY_EXCEEDED", 422, "rack capacity exceeded")
    ent = {
        "id": new_id(),
        "prep_list_id": plid,
        "prep_item_id": pid,
        "station_id": sid,
        "quantity": qty,
        "consumed_quantity": 0,
        "wasted_quantity": 0,
        "produced_at": None,
        "expires_at": None,
        "status": "PLANNED",
        "_seq": db.next_seq(),
        **new_entity(),
    }
    db.prep_batches[ent["id"]] = ent
    recompute_par_health(sid)
    return success_object(serialize(ent), status=201)


@bp.route("/api/prep-batches", methods=["GET"])
def list_batches():
    require_roles(*ALL_ROLES)
    page, limit, offset, total = list_paginated(
        db.prep_batches,
        [
            ("prep_list_id", "prep_list_id"),
            ("prep_item_id", "prep_item_id"),
            ("station_id", "station_id"),
            ("status", "status"),
        ],
        request.args,
    )
    return success_array([serialize(b) for b in page], limit, offset, total)


@bp.route("/api/prep-batches/<bid>", methods=["GET"])
def get_batch(bid):
    require_roles(*ALL_ROLES)
    b = resolve("prep_batch", bid)
    return success_object(serialize(b))


@bp.route("/api/prep-batches/<bid>/mark-prepped", methods=["POST"])
def mark_prepped(bid):
    get_user_context()
    get_json_body()
    require_roles("PrepCook")
    b = resolve("prep_batch", bid)
    if b["status"] != "PLANNED":
        raise ApiError("ERR_BATCH_NOT_PLANNED", 409, "mark-prepped requires PLANNED batch")
    now = clock_now()
    item = db.prep_items[b["prep_item_id"]]
    b["produced_at"] = format_iso(now)
    b["expires_at"] = format_iso(now + timedelta(hours=item["shelf_life_hours"]))
    b["status"] = "PREPPED"
    touch(b)
    # Parent list LOCKED -> IN_PROGRESS on first prepped batch
    pl = db.prep_lists.get(b["prep_list_id"])
    if pl is not None and pl["status"] == "LOCKED":
        pl["status"] = "IN_PROGRESS"
        touch(pl)
    recompute_par_health(b["station_id"])
    return success_object(serialize(b))


@bp.route("/api/prep-batches/<bid>/record-consumption", methods=["POST"])
def record_consumption(bid):
    get_user_context()
    body = get_json_body()
    require_fields(body, ["quantity"])
    qty = check_int(body, "quantity", min_value=1)
    require_roles("LineCook", "PrepCook")
    b = resolve("prep_batch", bid)
    if b["status"] != "PREPPED":
        raise ApiError("ERR_BATCH_NOT_PREPPED", 409, "record-consumption requires PREPPED batch")
    now = clock_now()
    expires = None
    if b["expires_at"] is not None:
        from services.common import parse_datetime_value
        expires = parse_datetime_value(b["expires_at"], "expires_at")
    if expires is not None and now >= expires:
        # Expiry beats consumption: transition to EXPIRED with auto waste entry
        remaining = b["quantity"] - b["consumed_quantity"] - b["wasted_quantity"]
        if remaining > 0:
            ent = {
                "id": new_id(),
                "station_id": b["station_id"],
                "prep_batch_id": b["id"],
                "quantity": remaining,
                "reason": "EXPIRED",
                "recorded_by_cook_id": None,
                "status": "ATTRIBUTED",
                "_seq": db.next_seq(),
                **new_entity(),
            }
            db.waste_entries[ent["id"]] = ent
            b["wasted_quantity"] += remaining
        finalize_batch_terminal(b, "EXPIRED")
        raise ApiError("ERR_BATCH_EXPIRED", 409, "Batch is expired")
    b["consumed_quantity"] += qty
    touch(b)
    if b["consumed_quantity"] + b["wasted_quantity"] >= b["quantity"]:
        finalize_batch_terminal(b, "DEPLETED")
    else:
        recompute_par_health(b["station_id"])
    return success_object(serialize(b))


@bp.route("/api/prep-batches/<bid>/expire", methods=["POST"])
def expire(bid):
    get_user_context()
    get_json_body()
    require_roles("KitchenManager")
    b = resolve("prep_batch", bid)
    if b["status"] not in ("PLANNED", "PREPPED"):
        raise ApiError("ERR_INVALID_TRANSITION", 409, "expire requires PLANNED or PREPPED batch")
    if b["status"] == "PLANNED" or b["expires_at"] is None:
        raise ApiError("ERR_BATCH_NOT_PREPPED", 409, "A PLANNED batch's expiry is never due")
    from services.common import parse_datetime_value
    expires = parse_datetime_value(b["expires_at"], "expires_at")
    if clock_now() < expires:
        raise ApiError("ERR_INVALID_TRANSITION", 409, "Batch shelf life has not run out")
    remaining = b["quantity"] - b["consumed_quantity"] - b["wasted_quantity"]
    if remaining > 0:
        ent = {
            "id": new_id(),
            "station_id": b["station_id"],
            "prep_batch_id": b["id"],
            "quantity": remaining,
            "reason": "EXPIRED",
            "recorded_by_cook_id": None,
            "status": "ATTRIBUTED",
            "_seq": db.next_seq(),
            **new_entity(),
        }
        db.waste_entries[ent["id"]] = ent
        b["wasted_quantity"] += remaining
    finalize_batch_terminal(b, "EXPIRED")
    return success_object(serialize(b))
