"""Reimbursement schedules (PRD 3.7) and the safe-drop procedure (PRD 3.10)."""
from flask import Blueprint

import auth
import calc
import clock
import db
import derive
import listing
import response
import serialize
import validate
from errors import fail

bp = Blueprint("fleet", __name__)

VEHICLE_CLASSES = ("CAR", "SUV", "SCOOTER")
COST_MODEL_STATUSES = ("ACTIVE", "RETIRED")
SAFE_DROP_STATUSES = ("RECORDED", "VOIDED")
VOID_WINDOW_SECONDS = 3600


@bp.post("/store-ops/vehicle-cost-models")
def publish_cost_model():
    actor = auth.authenticate(["StoreManager"])
    auth.guard(actor, [], [("store_id", "store")])
    body = validate.body()
    raw_store_id = body.get("store_id")
    store = None
    if isinstance(raw_store_id, str) and raw_store_id != "":
        store = auth.body_fk("store", raw_store_id)
    validate.string(body, "store_id")
    vehicle_class = validate.enum(body, "vehicle_class", VEHICLE_CLASSES)
    per_delivery = validate.integer(body, "per_delivery_cents", minimum=0)
    cap_miles = validate.miles(body, "tier1_cap_miles", strictly_positive=True)
    tier1 = validate.integer(body, "tier1_per_mile_cents", minimum=0)
    tier2 = validate.integer(body, "tier2_per_mile_cents", minimum=0)
    floor_cents = validate.integer(body, "min_reimbursement_per_stop_cents", minimum=0)
    effective_from = validate.instant(body, "effective_from")
    superseded = [
        m
        for m in db.cost_models.values()
        if m["store_id"] == store["id"]
        and m["vehicle_class"] == vehicle_class
        and m["status"] == "ACTIVE"
        and m["effective_from"] < effective_from
    ]
    for model in db.ordered(superseded):
        model["status"] = "RETIRED"
        model["retired_at"] = clock.now()
        db.touch(model)
    record = {
        "store_id": store["id"],
        "vehicle_class": vehicle_class,
        "per_delivery_cents": per_delivery,
        "tier1_cap_miles": cap_miles,
        "tier1_per_mile_cents": tier1,
        "tier2_per_mile_cents": tier2,
        "min_reimbursement_per_stop_cents": floor_cents,
        "effective_from": effective_from,
        "status": "ACTIVE",
        "retired_at": None,
    }
    db.insert(db.cost_models, record)
    return response.created(serialize.vehicle_cost_model(record))


@bp.get("/store-ops/vehicle-cost-models/<vehicle_cost_model_id>")
def read_cost_model(vehicle_cost_model_id):
    actor = auth.authenticate(auth.ALL_ROLES)
    (model,) = auth.guard(actor, [("vehicle_cost_model", vehicle_cost_model_id)])
    return response.ok(serialize.vehicle_cost_model(model))


@bp.get("/store-ops/vehicle-cost-models")
def list_cost_models():
    actor = auth.authenticate(auth.ALL_ROLES)
    store_id = validate.filter_string("store_id")
    vehicle_class = validate.filter_enum("vehicle_class", VEHICLE_CLASSES)
    status = validate.filter_enum("status", COST_MODEL_STATUSES)
    records = list(db.cost_models.values())
    if actor.is_manager:
        records = [m for m in records if m["store_id"] == actor.user_id]
    if store_id is not None:
        records = [m for m in records if m["store_id"] == store_id]
    if vehicle_class is not None:
        records = [m for m in records if m["vehicle_class"] == vehicle_class]
    if status is not None:
        records = [m for m in records if m["status"] == status]
    return listing.respond(records, serialize.vehicle_cost_model)


@bp.post("/store-ops/drivers/<driver_id>/safe-drops")
def record_safe_drop(driver_id):
    actor = auth.authenticate(["Driver", "StoreManager"])
    (driver,) = auth.guard(actor, [("driver", driver_id)])
    body = validate.body()
    amount = validate.integer(body, "amount_cents", minimum=1)
    envelope_number = validate.string(body, "envelope_number")
    if amount > derive.driver_cash_on_hand(driver["id"]):
        fail("ERR_SAFE_DROP_EXCEEDS_CASH", "The drop exceeds the driver's cash on hand.")
    record = {
        "driver_id": driver["id"],
        "amount_cents": amount,
        "envelope_number": envelope_number,
        "status": "RECORDED",
        "voided_reason": None,
        "voided_at": None,
    }
    db.insert(db.safe_drops, record)
    db.touch(driver)
    store = db.stores.get(driver["store_id"])
    if store is not None:
        db.touch(store)
    return response.created(serialize.safe_drop(record))


@bp.post("/store-ops/safe-drops/<safe_drop_id>/void")
def void_safe_drop(safe_drop_id):
    actor = auth.authenticate(["StoreManager"])
    (drop,) = auth.guard(actor, [("safe_drop", safe_drop_id)])
    body = validate.body()
    voided_reason = validate.string(body, "voided_reason")
    if drop["status"] != "RECORDED":
        fail("ERR_INVALID_SAFE_DROP_STATE", "Only a RECORDED drop can be voided.")
    if clock.whole_seconds(clock.now(), drop["created_at"]) >= VOID_WINDOW_SECONDS:
        fail("ERR_SAFE_DROP_NOT_VOIDABLE", "The 60-minute void window has closed.")
    drop["status"] = "VOIDED"
    drop["voided_reason"] = voided_reason
    drop["voided_at"] = clock.now()
    db.touch(drop)
    driver = db.drivers.get(drop["driver_id"])
    if driver is not None:
        db.touch(driver)
        store = db.stores.get(driver["store_id"])
        if store is not None:
            db.touch(store)
    return response.ok(serialize.safe_drop(drop))


@bp.get("/store-ops/safe-drops/<safe_drop_id>")
def read_safe_drop(safe_drop_id):
    actor = auth.authenticate(["StoreManager", "Dispatcher", "Driver", "ComplianceOfficer"])
    (drop,) = auth.guard(actor, [("safe_drop", safe_drop_id)])
    return response.ok(serialize.safe_drop(drop))


@bp.get("/store-ops/safe-drops")
def list_safe_drops():
    actor = auth.authenticate(["StoreManager", "Dispatcher", "Driver", "ComplianceOfficer"])
    driver_id = validate.filter_string("driver_id")
    status = validate.filter_enum("status", SAFE_DROP_STATUSES)
    records = list(db.safe_drops.values())
    if actor.is_manager:
        records = [d for d in records if auth.owning_store_id("safe_drop", d) == actor.user_id]
    elif actor.is_driver:
        records = [d for d in records if d["driver_id"] == actor.user_id]
    if driver_id is not None:
        records = [d for d in records if d["driver_id"] == driver_id]
    if status is not None:
        records = [d for d in records if d["status"] == status]
    return listing.respond(records, serialize.safe_drop)
