"""Allotments, the shared pool and restrictions (PRD 3.7, 3.8)."""

from flask import Blueprint

import calc
import cascade
import guards
import refs
import serialize
import shape
import store
from envelope import created, ok
from errors import fail
from guards import must, page
from refs import get, put, rows, where

bp = Blueprint("inventory", __name__)

INTERNAL = shape.INTERNAL_ROLES
ALLOCATION_STATES = ("OPEN", "EXHAUSTED", "RELEASED", "RECALLED", "SUPERSEDED")
RESTRICTION_TYPES = ("MIN_STAY", "CLOSED_TO_ARRIVAL", "STOP_SELL")
RESTRICTION_STATES = ("ACTIVE", "LIFTED")


@bp.post("/distribution/room-types/<rid>/allocations")
def create_allocation(rid):
    shape.auth("RevenueManager")
    room_type = must("room_types", rid, "ERR_ROOM_TYPE_NOT_FOUND")
    prop = refs.prop_of_room_type(room_type)
    body = shape.body_obj()
    channel_id = shape.v_string(body, "channel_id", required=True)
    units = shape.v_int(body, "allocated_units", required=True, lo=1, hi=500)
    start_date = shape.v_date(body, "start_date", required=True)
    end_date = shape.v_date(body, "end_date", required=True)
    echo = shape.v_int(body, "expected_room_type_version", required=True, lo=0)
    if end_date < start_date:
        fail("ERR_INVALID_REQUEST", "Field 'end_date' must not precede 'start_date'.")
    channel = get("channels", channel_id)
    if channel is None:
        fail("ERR_CHANNEL_NOT_FOUND")
    if channel["property_id"] != room_type["property_id"]:
        fail("ERR_PROPERTY_SCOPE_MISMATCH")
    if echo != room_type["version"]:
        fail("ERR_STALE_ROOM_TYPE_VERSION")
    span = refs.day_span(start_date, end_date)
    days = {}
    for day_s in span:
        day = refs.inventory_day(room_type["id"], day_s)
        if day is None:
            fail("ERR_INVENTORY_DAY_NOT_OPEN")
        days[day_s] = day
    guards.require_horizon(prop, [start_date, end_date])
    predecessor = None
    for existing in where("allocations", room_type_id=room_type["id"]):
        if existing["channel_id"] != channel["id"]:
            continue
        if existing["start_date"] != start_date or existing["end_date"] != end_date:
            continue
        if existing["allocation_state"] not in ("OPEN", "EXHAUSTED"):
            continue
        predecessor = existing
    exclude = (predecessor["id"],) if predecessor is not None else ()
    for day_s in span:
        held = calc.held_units_on(room_type["id"], day_s, exclude_ids=exclude)
        committed = calc.committed_units_on(room_type["id"], day_s)
        if held + committed + units > days[day_s]["overbooking_ceiling_units"]:
            fail("ERR_ALLOCATION_EXCEEDS_CEILING")
    if predecessor is not None:
        predecessor["allocation_state"] = "SUPERSEDED"
        predecessor["superseded_at"] = store.now_iso()
        store.bump(predecessor)
    rec = store.base_record()
    rec.update({
        "room_type_id": room_type["id"],
        "channel_id": channel["id"],
        "allocated_units": units,
        "start_date": start_date,
        "end_date": end_date,
        "consumed_units": 0,
        "allocation_state": "OPEN",
        "superseded_at": None,
        "recalled_at": None,
    })
    put("allocations", rec)
    cascade.refresh_room_type(room_type["id"])
    store.bump(room_type)
    return created(serialize.allocation_out(rec))


@bp.post("/distribution/allocations/<aid>/release")
def release_allocation(aid):
    shape.auth("RevenueManager")
    alloc = must("allocations", aid, "ERR_ALLOCATION_NOT_FOUND")
    if alloc["allocation_state"] not in ("OPEN", "EXHAUSTED"):
        fail("ERR_ALLOCATION_STATE_INVALID")
    alloc["allocation_state"] = "RELEASED"
    store.bump(alloc)
    cascade.refresh_days(alloc["room_type_id"])
    return ok(serialize.allocation_out(alloc))


@bp.get("/distribution/allocations")
def list_allocations():
    shape.auth(*INTERNAL)
    room_type_id = shape.q_id("room_type_id")
    channel_id = shape.q_id("channel_id")
    state = shape.q_enum("allocation_state", ALLOCATION_STATES)
    records = rows("allocations")
    if room_type_id is not None:
        records = [r for r in records if r["room_type_id"] == room_type_id]
    if channel_id is not None:
        records = [r for r in records if r["channel_id"] == channel_id]
    if state is not None:
        records = [r for r in records if r["allocation_state"] == state]
    return page(serialize.allocation_out, records)


@bp.get("/distribution/allocations/<aid>")
def read_allocation(aid):
    shape.auth(*INTERNAL)
    alloc = must("allocations", aid, "ERR_ALLOCATION_NOT_FOUND")
    return ok(serialize.allocation_out(alloc))


@bp.post("/distribution/restrictions")
def create_restriction():
    shape.auth("RevenueManager")
    body = shape.body_obj()
    room_type_id = shape.v_string(body, "room_type_id", required=True)
    restriction_type = shape.v_enum(body, "restriction_type", RESTRICTION_TYPES,
                                    required=True)
    start_date = shape.v_date(body, "start_date", required=True)
    end_date = shape.v_date(body, "end_date", required=True)
    rate_plan_id = shape.v_string(body, "rate_plan_id")
    value_nights = shape.v_int(body, "value_nights", lo=2, hi=14)
    if end_date < start_date:
        fail("ERR_INVALID_REQUEST", "Field 'end_date' must not precede 'start_date'.")
    if restriction_type == "MIN_STAY":
        if value_nights is None:
            fail("ERR_INVALID_REQUEST",
                 "Field 'value_nights' is required for a MIN_STAY restriction.")
    elif value_nights is not None:
        fail("ERR_INVALID_REQUEST",
             "Field 'value_nights' is only valid for a MIN_STAY restriction.")
    room_type = get("room_types", room_type_id)
    if room_type is None:
        fail("ERR_ROOM_TYPE_NOT_FOUND")
    plan = None
    if rate_plan_id is not None:
        plan = get("rate_plans", rate_plan_id)
        if plan is None:
            fail("ERR_RATE_PLAN_NOT_FOUND")
        if plan["property_id"] != room_type["property_id"]:
            fail("ERR_PROPERTY_SCOPE_MISMATCH")
    prop = refs.prop_of_room_type(room_type)
    guards.require_horizon(prop, [start_date, end_date])
    for existing in where("restrictions", room_type_id=room_type["id"]):
        if existing["restriction_state"] != "ACTIVE":
            continue
        if existing["rate_plan_id"] != rate_plan_id:
            continue
        if existing["restriction_type"] != restriction_type:
            continue
        if existing["origin"] != "MANUAL":
            continue
        if existing["start_date"] <= end_date and start_date <= existing["end_date"]:
            fail("ERR_RESTRICTION_WINDOW_OVERLAP")
    rec = store.base_record()
    rec.update({
        "room_type_id": room_type["id"],
        "rate_plan_id": rate_plan_id,
        "restriction_type": restriction_type,
        "start_date": start_date,
        "end_date": end_date,
        "value_nights": value_nights,
        "origin": "MANUAL",
        "restriction_state": "ACTIVE",
        "lifted_at": None,
        "lift_reason": None,
    })
    put("restrictions", rec)
    cascade.restriction_batch(rec)
    return created(serialize.restriction_out(rec))


@bp.post("/distribution/restrictions/<rid>/lift")
def lift_restriction(rid):
    shape.auth("RevenueManager")
    restriction = must("restrictions", rid, "ERR_RESTRICTION_NOT_FOUND")
    if restriction["origin"] == "AUTO_OVERBOOK_GUARD":
        fail("ERR_OVERRIDE_NOT_PERMITTED",
             "An automatic overbooking guard is system-owned.")
    if restriction["restriction_state"] != "ACTIVE":
        fail("ERR_RESTRICTION_STATE_INVALID")
    restriction["restriction_state"] = "LIFTED"
    restriction["lifted_at"] = store.now_iso()
    restriction["lift_reason"] = "MANUAL_LIFT"
    store.bump(restriction)
    cascade.restriction_batch(restriction)
    return ok(serialize.restriction_out(restriction))


@bp.get("/distribution/restrictions")
def list_restrictions():
    shape.auth(*INTERNAL)
    room_type_id = shape.q_id("room_type_id")
    rate_plan_id = shape.q_id("rate_plan_id")
    restriction_type = shape.q_enum("restriction_type", RESTRICTION_TYPES)
    state = shape.q_enum("restriction_state", RESTRICTION_STATES)
    records = rows("restrictions")
    if room_type_id is not None:
        records = [r for r in records if r["room_type_id"] == room_type_id]
    if rate_plan_id is not None:
        records = [r for r in records if r["rate_plan_id"] == rate_plan_id]
    if restriction_type is not None:
        records = [r for r in records if r["restriction_type"] == restriction_type]
    if state is not None:
        records = [r for r in records if r["restriction_state"] == state]
    return page(serialize.restriction_out, records)


@bp.get("/distribution/restrictions/<rid>")
def read_restriction(rid):
    shape.auth(*INTERNAL)
    restriction = must("restrictions", rid, "ERR_RESTRICTION_NOT_FOUND")
    return ok(serialize.restriction_out(restriction))
