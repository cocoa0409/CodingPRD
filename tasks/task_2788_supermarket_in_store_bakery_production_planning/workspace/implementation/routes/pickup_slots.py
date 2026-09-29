"""Pickup slot endpoints: the half-open decorator window (PRD 3.7)."""

from flask import Blueprint, request

import serializers
from errors import ApiError
from guards import (
    ANY_ROLE,
    SLOT_STATUSES,
    as_datetime,
    as_int,
    authenticate,
    bad,
    body,
    enum_filter,
    find_bake_day,
    find_slot,
    scope,
)
from response import created, listing, mark_new, ok, parse_pagination, touch
from services.calc import slots_overlap
from store import by_seq, db, new_entity

bp = Blueprint("pickup_slots", __name__)


@bp.post("/bakery/pickup-slots")
def create_pickup_slot():
    caller = authenticate(("CakeDesk", "DepartmentManager"))
    payload = body()
    day = find_bake_day(payload.get("bake_day_id"))
    scope(caller, day["department_id"])

    slot_start = as_datetime(payload, "slot_start_utc")
    slot_end = as_datetime(payload, "slot_end_utc")
    if slot_end <= slot_start:
        bad("slot_end_utc", "must be strictly after slot_start_utc.")
    capacity = as_int(payload, "decorator_capacity_units", minimum=1, maximum=500)

    if day["plan_posture"] == "CLOSED":
        raise ApiError("ERR_BAKE_DAY_CLOSED")

    for existing in db.pickup_slots.values():
        if existing["bake_day_id"] != day["id"]:
            continue
        if slots_overlap(slot_start, slot_end, existing["slot_start_utc"], existing["slot_end_utc"]):
            raise ApiError("ERR_PICKUP_SLOT_OVERLAP")

    row = new_entity(
        bake_day_id=day["id"],
        slot_start_utc=slot_start,
        slot_end_utc=slot_end,
        decorator_capacity_units=capacity,
        reserved_decoration_units=0,
        slot_status="OPEN",
    )
    db.pickup_slots[row["id"]] = row
    mark_new(row)
    return created(serializers.pickup_slot(row))


@bp.get("/bakery/pickup-slots/<pickupSlotId>")
def read_pickup_slot(pickupSlotId):
    authenticate(ANY_ROLE)
    return ok(serializers.pickup_slot(find_slot(pickupSlotId)))


@bp.get("/bakery/pickup-slots")
def list_pickup_slots():
    authenticate(ANY_ROLE)
    limit, offset = parse_pagination(request.args)
    bake_day_id = request.args.get("bake_day_id") or None
    status = enum_filter(request.args, "slot_status", SLOT_STATUSES)
    rows = []
    for row in db.pickup_slots.values():
        if bake_day_id is not None and row["bake_day_id"] != bake_day_id:
            continue
        if status is not None and row["slot_status"] != status:
            continue
        rows.append(row)
    return listing([serializers.pickup_slot(row) for row in by_seq(rows)], limit, offset)


@bp.post("/bakery/pickup-slots/<pickupSlotId>/close")
def close_pickup_slot(pickupSlotId):
    caller = authenticate(("CakeDesk", "DepartmentManager"))
    slot = find_slot(pickupSlotId)
    day = db.bake_days.get(slot["bake_day_id"])
    scope(caller, day["department_id"] if day else None)

    if day is not None and day["plan_posture"] == "CLOSED":
        raise ApiError("ERR_BAKE_DAY_CLOSED")
    if slot["slot_status"] != "OPEN":
        raise ApiError("ERR_PICKUP_SLOT_CLOSED")

    slot["slot_status"] = "CLOSED"
    touch(slot)
    return ok(serializers.pickup_slot(slot))
