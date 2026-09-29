"""Store registration, policy edits and the cash-reconciliation read (PRD 3.1, 3.10)."""
from flask import Blueprint

import auth
import db
import derive
import response
import serialize
import validate
from errors import fail

bp = Blueprint("stores", __name__)

SERVICE_POSTURES = ("OPEN", "CARRYOUT_ONLY", "CLOSED")
READ_ROLES = auth.ALL_ROLES

POLICY_FIELDS = (
    ("promise_minutes", 30, 1),
    ("delivery_fee_cents", 399, 0),
    ("cash_limit_cents", 5000, 0),
    ("hot_bag_count", 4, 1),
    ("max_stacked_stops", 3, 1),
    ("handoff_minutes_per_stop", 6, 0),
    ("dispatch_reset_buffer_minutes", 10, 0),
)


def _store_number_taken(store_number, exclude_id=None):
    for store in db.stores.values():
        if store["store_number"] == store_number and store["id"] != exclude_id:
            return True
    return False


@bp.post("/store-ops/stores")
def create_store():
    # Registration is the one StoreManager call with no target to scope against.
    auth.authenticate(["StoreManager"])
    body = validate.body()
    store_number = validate.string(body, "store_number", min_len=1, max_len=8)
    name = validate.string(body, "name")
    latitude = validate.integer(body, "latitude_micro", minimum=-90000000, maximum=90000000)
    longitude = validate.integer(body, "longitude_micro", minimum=-180000000, maximum=180000000)
    record = {
        "store_number": store_number,
        "name": name,
        "latitude_micro": latitude,
        "longitude_micro": longitude,
    }
    for field, default, minimum in POLICY_FIELDS:
        record[field] = validate.integer(
            body, field, required=False, default=default, minimum=minimum
        )
    record["service_posture"] = validate.enum(
        body, "service_posture", SERVICE_POSTURES, required=False, default="OPEN"
    )
    if _store_number_taken(store_number):
        fail("ERR_STORE_NUMBER_TAKEN", "Store number %s is already registered." % store_number)
    db.insert(db.stores, record)
    return response.created(serialize.store(record))


@bp.patch("/store-ops/stores/<store_id>")
def edit_store(store_id):
    actor = auth.authenticate(["StoreManager"])
    (store,) = auth.guard(actor, [("store", store_id)])
    body = validate.body()
    updates = {}
    if "store_number" in body:
        updates["store_number"] = validate.string(body, "store_number", min_len=1, max_len=8)
    if "name" in body:
        updates["name"] = validate.string(body, "name")
    for field, _default, minimum in POLICY_FIELDS:
        if field in body:
            updates[field] = validate.integer(body, field, minimum=minimum)
    if "service_posture" in body:
        updates["service_posture"] = validate.enum(body, "service_posture", SERVICE_POSTURES)
    if "store_number" in updates and _store_number_taken(updates["store_number"], store["id"]):
        fail(
            "ERR_STORE_NUMBER_TAKEN",
            "Store number %s is already registered." % updates["store_number"],
        )
    store.update(updates)
    db.touch(store)
    return response.ok(serialize.store(store))


@bp.get("/store-ops/stores/<store_id>")
def read_store(store_id):
    actor = auth.authenticate(READ_ROLES)
    (store,) = auth.guard(actor, [("store", store_id)])
    return response.ok(serialize.store(store))


@bp.get("/store-ops/stores/<store_id>/cash-reconciliation")
def cash_reconciliation(store_id):
    actor = auth.authenticate(["StoreManager"])
    (store,) = auth.guard(actor, [("store", store_id)])
    collected = derive.store_cash_collected(store["id"])
    deposited = derive.store_safe_deposit(store["id"])
    on_hand = derive.store_driver_cash_total(store["id"])
    return response.ok(
        {
            "store_id": store["id"],
            "cash_collected_total_cents": collected,
            "safe_deposit_total_cents": deposited,
            "driver_cash_on_hand_total_cents": on_hand,
            "reconciled": collected == deposited + on_hand,
        }
    )
