"""Properties, room types and the sellable calendar (PRD 3.1)."""

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
from refs import put, rows, where

bp = Blueprint("property", __name__)

INTERNAL = shape.INTERNAL_ROLES
POOLED_STATES = ("OPEN", "TIGHT", "EXHAUSTED", "OVERSOLD")


@bp.post("/distribution/properties")
def create_property():
    shape.auth("PlatformAdmin")
    body = shape.body_obj()
    code = shape.v_string(body, "code", required=True, minlen=3, maxlen=16,
                          pattern=r"^[A-Z0-9-]+$")
    name = shape.v_string(body, "name", required=True, minlen=1, maxlen=120)
    currency = shape.v_string(body, "currency_code", default="USD", minlen=3,
                              maxlen=3, pattern=r"^[A-Z]{3}$")
    overbooking = shape.v_int(body, "overbooking_pct_bp", default=0, lo=0, hi=5000)
    horizon = shape.v_int(body, "booking_horizon_days", default=365, lo=1, hi=730)
    mix_window = shape.v_int(body, "mix_window_days", default=30, lo=1, hi=90)
    tolerance = shape.v_int(body, "rate_mismatch_tolerance_cents", default=0, lo=0)
    images = shape.v_int(body, "required_image_count", default=0, lo=0)
    for existing in rows("properties"):
        if existing["code"] == code:
            fail("ERR_DUPLICATE_RESOURCE", "Property code %s is already in use." % code)
    rec = store.base_record()
    rec.update({
        "code": code,
        "name": name,
        "currency_code": currency,
        "overbooking_pct_bp": overbooking,
        "booking_horizon_days": horizon,
        "mix_window_days": mix_window,
        "rate_mismatch_tolerance_cents": tolerance,
        "required_image_count": images,
    })
    put("properties", rec)
    return created(serialize.property_out(rec))


@bp.get("/distribution/properties")
def list_properties():
    shape.auth(*INTERNAL)
    return page(serialize.property_out, rows("properties"))


@bp.get("/distribution/properties/<pid>")
def read_property(pid):
    shape.auth(*INTERNAL)
    prop = must("properties", pid, "ERR_PROPERTY_NOT_FOUND")
    return ok(serialize.property_out(prop))


@bp.post("/distribution/properties/<pid>/room-types")
def create_room_type(pid):
    shape.auth("PlatformAdmin", "RevenueManager")
    prop = must("properties", pid, "ERR_PROPERTY_NOT_FOUND")
    body = shape.body_obj()
    code = shape.v_string(body, "code", required=True, minlen=2, maxlen=12,
                          pattern=r"^[A-Z0-9]+$")
    name = shape.v_string(body, "name", required=True, minlen=1, maxlen=120)
    capacity = shape.v_int(body, "physical_capacity_units", required=True, lo=1, hi=500)
    master_hash = shape.v_string(body, "master_description_hash", required=True,
                                 minlen=4, maxlen=64, pattern=r"^[a-z0-9]+$")
    master_images = shape.v_int(body, "master_image_count", required=True, lo=0, hi=40)
    overbooking = shape.v_int(body, "overbooking_pct_bp", default=None, lo=0, hi=5000)
    for existing in where("room_types", property_id=prop["id"]):
        if existing["code"] == code:
            fail("ERR_DUPLICATE_RESOURCE",
                 "Room type code %s already exists on this property." % code)
    rec = store.base_record()
    rec.update({
        "property_id": prop["id"],
        "code": code,
        "name": name,
        "physical_capacity_units": capacity,
        "overbooking_pct_bp": overbooking,
        "master_description_hash": master_hash,
        "master_image_count": master_images,
    })
    put("room_types", rec)
    return created(serialize.room_type_out(rec))


@bp.patch("/distribution/room-types/<rid>")
def update_room_type(rid):
    shape.auth("RevenueManager")
    room_type = must("room_types", rid, "ERR_ROOM_TYPE_NOT_FOUND")
    body = shape.body_obj()
    name = shape.v_string(body, "name", minlen=1, maxlen=120, nullable=False)
    capacity = shape.v_int(body, "physical_capacity_units", lo=1, hi=500, nullable=False)
    master_hash = shape.v_string(body, "master_description_hash", minlen=4, maxlen=64,
                                 pattern=r"^[a-z0-9]+$", nullable=False)
    master_images = shape.v_int(body, "master_image_count", lo=0, hi=40, nullable=False)
    overbooking_sent = "overbooking_pct_bp" in body
    overbooking = shape.v_int(body, "overbooking_pct_bp", lo=0, hi=5000)
    previous_hash = room_type["master_description_hash"]
    if name is not None:
        room_type["name"] = name
    if capacity is not None:
        room_type["physical_capacity_units"] = capacity
    if master_hash is not None:
        room_type["master_description_hash"] = master_hash
    if master_images is not None:
        room_type["master_image_count"] = master_images
    if overbooking_sent:
        room_type["overbooking_pct_bp"] = overbooking
    store.bump(room_type)
    if room_type["master_description_hash"] != previous_hash:
        cascade.reparity_room_type(room_type["id"])
    cascade.refresh_room_type(room_type["id"])
    return ok(serialize.room_type_out(room_type))


@bp.get("/distribution/room-types")
def list_room_types():
    shape.auth(*INTERNAL)
    property_id = shape.q_id("property_id")
    records = rows("room_types")
    if property_id is not None:
        records = [r for r in records if r["property_id"] == property_id]
    return page(serialize.room_type_out, records)


@bp.get("/distribution/room-types/<rid>")
def read_room_type(rid):
    shape.auth(*INTERNAL)
    room_type = must("room_types", rid, "ERR_ROOM_TYPE_NOT_FOUND")
    return ok(serialize.room_type_out(room_type))


@bp.post("/distribution/room-types/<rid>/inventory-days")
def create_inventory_day(rid):
    shape.auth("RevenueManager")
    room_type = must("room_types", rid, "ERR_ROOM_TYPE_NOT_FOUND")
    prop = refs.prop_of_room_type(room_type)
    body = shape.body_obj()
    stay_date = shape.v_date(body, "stay_date", required=True)
    guards.require_horizon(prop, [stay_date])
    if refs.inventory_day(room_type["id"], stay_date) is not None:
        fail("ERR_DUPLICATE_RESOURCE",
             "Stay date %s is already open on this room type." % stay_date)
    rec = store.base_record()
    rec.update({"room_type_id": room_type["id"], "stay_date": stay_date})
    rec.update(calc.day_numbers(rec))
    put("inventory_days", rec)
    return created(serialize.inventory_day_out(rec))


@bp.get("/distribution/inventory-days")
def list_inventory_days():
    shape.auth(*INTERNAL)
    room_type_id = shape.q_id("room_type_id")
    date_from = shape.q_date("stay_date_from")
    date_to = shape.q_date("stay_date_to")
    pooled_state = shape.q_enum("pooled_state", POOLED_STATES)
    records = rows("inventory_days")
    if room_type_id is not None:
        records = [r for r in records if r["room_type_id"] == room_type_id]
    if date_from is not None:
        records = [r for r in records if r["stay_date"] >= date_from]
    if date_to is not None:
        records = [r for r in records if r["stay_date"] <= date_to]
    if pooled_state is not None:
        records = [r for r in records if r["pooled_state"] == pooled_state]
    return page(serialize.inventory_day_out, records)


@bp.get("/distribution/inventory-days/<did>")
def read_inventory_day(did):
    shape.auth(*INTERNAL)
    day = must("inventory_days", did, "ERR_INVENTORY_DAY_NOT_FOUND")
    return ok(serialize.inventory_day_out(day))
