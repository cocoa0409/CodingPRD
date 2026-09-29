"""Order intake, pricing, disclosure, zone disposition and the make line
(PRD 3.4, 3.5) plus the remake policy (PRD 3.12)."""
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

bp = Blueprint("orders", __name__)

READ_ROLES = auth.ALL_ROLES
PAYMENT_METHODS = ("CASH", "CARD")
FULFILMENT_STATUSES = (
    "PLACED",
    "ZONE_HELD",
    "ZONE_CLEARED",
    "IN_PRODUCTION",
    "READY",
    "ASSIGNED",
    "EN_ROUTE",
    "DELIVERED",
    "REMAKE_QUEUED",
    "CLOSED",
    "DECLINED_OUT_OF_AREA",
    "CARRYOUT_REDIRECTED",
)
SETTLEMENT_STATUSES = (
    "UNDISCLOSED",
    "DISCLOSED",
    "CHARGED",
    "ADJUSTED",
    "CLOSED_SETTLED",
    "VOIDED",
)
ZONE_ACTIONS = ("CLEAR", "HOLD", "DECLINE", "REDIRECT_CARRYOUT")
ZONE_ACTION_FROM = {
    "CLEAR": ("PLACED", "ZONE_HELD"),
    "HOLD": ("PLACED",),
    "DECLINE": ("PLACED", "ZONE_HELD"),
    "REDIRECT_CARRYOUT": ("PLACED", "ZONE_HELD"),
}
REMAKE_GRACE_MINUTES = 5


def accrue_zone_hold(order):
    """Whole minutes parked, truncated downward (PRD 3.3, 3.5)."""
    if order["zone_held_at"] is None:
        return
    order["zone_hold_minutes"] = order["zone_hold_minutes"] + clock.elapsed_minutes_floor(
        clock.now(), order["zone_held_at"]
    )


@bp.post("/store-ops/orders")
def take_order():
    auth.authenticate(["Dispatcher", "CustomerCareAgent"])
    body = validate.body()
    raw_store_id = body.get("store_id")
    store = None
    if isinstance(raw_store_id, str) and raw_store_id != "":
        store = auth.body_fk("store", raw_store_id)
    raw_address_id = body.get("service_address_id")
    address = None
    if isinstance(raw_address_id, str) and raw_address_id != "":
        address = auth.body_fk("service_address", raw_address_id)
        if store is not None and address["store_id"] != store["id"]:
            # An address of another store is reported as not found, not as a scope error.
            fail("ERR_SERVICE_ADDRESS_NOT_FOUND", "That address belongs to another store.")
    validate.string(body, "store_id")
    validate.string(body, "service_address_id")
    customer_name = validate.string(body, "customer_name")
    customer_phone = validate.string(body, "customer_phone")
    food_subtotal = validate.integer(body, "food_subtotal_cents", minimum=0)
    payment_method = validate.enum(body, "payment_method", PAYMENT_METHODS)
    tip_cents = validate.integer(body, "tip_cents", required=False, default=0, minimum=0)
    pricing = calc.price_order(
        store, address["drive_time_estimate_minutes"], food_subtotal, tip_cents
    )
    record = {
        "store_id": store["id"],
        "service_address_id": address["id"],
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        "food_subtotal_cents": food_subtotal,
        "tip_cents": tip_cents,
        "payment_method": payment_method,
        "fulfillment_status": "PLACED",
        "settlement_status": "UNDISCLOSED",
        "promise_minutes_snapshot": store["promise_minutes"],
        "disclosed_fee_cents": None,
        "disclosed_tip_cents": None,
        "driver_tip_notice_given": False,
        "fee_disclosure_accurate": None,
        "fee_disclosed_at": None,
        "placed_at": clock.now(),
        "ready_at": None,
        "door_arrival_at": None,
        "zone_held_at": None,
        "zone_hold_minutes": 0,
        "remake_hold_minutes": 0,
        "remake_count": 0,
        "order_to_door_gross_minutes": None,
        "order_to_door_net_minutes": None,
        "cash_collected_cents": 0,
        "remedy_issued_cents": 0,
        "remake_credit_cents": 0,
        "declined_reason": None,
    }
    record.update(pricing)
    if store["service_posture"] == "CARRYOUT_ONLY":
        record["fulfillment_status"] = "CARRYOUT_REDIRECTED"
        record["declined_reason"] = "STORE_CARRYOUT_ONLY"
        record["settlement_status"] = "VOIDED"
    db.insert(db.orders, record)
    return response.created(serialize.order(record))


@bp.post("/store-ops/orders/<order_id>/zone-decision")
def zone_decision(order_id):
    actor = auth.authenticate(["Dispatcher", "StoreManager"])
    (order,) = auth.guard(actor, [("order", order_id)])
    body = validate.body()
    action = validate.enum(body, "action", ZONE_ACTIONS)
    validate.string(body, "note", required=False, min_len=None)
    if order["fulfillment_status"] not in ZONE_ACTION_FROM[action]:
        fail(
            "ERR_INVALID_ORDER_STATE",
            "Action %s is not declared from %s." % (action, order["fulfillment_status"]),
        )
    store = db.stores.get(order["store_id"])
    address = db.service_addresses.get(order["service_address_id"])
    if derive.in_force_zone_version(order["store_id"]) is None:
        fail("ERR_NO_ACTIVE_ZONE_VERSION", "The store has no delivery area in force.")
    effective = derive.effective_zone_state(address) if address else None
    if action == "CLEAR":
        if effective != "IN_ZONE":
            fail("ERR_ADDRESS_OUT_OF_AREA", "The destination does not read as IN_ZONE.")
        if store["service_posture"] != "OPEN":
            fail("ERR_STORE_NOT_ACCEPTING_DELIVERY", "The store is not accepting deliveries.")
    elif action == "HOLD":
        if effective not in ("EDGE", "OUT_OF_ZONE"):
            fail("ERR_ZONE_HOLD_NOT_APPLICABLE", "An accepted address cannot be parked for review.")
    else:
        if effective not in ("EDGE", "OUT_OF_ZONE"):
            fail("ERR_DECLINE_NOT_APPLICABLE", "The store owes an in-zone address a delivery.")
    if action == "CLEAR":
        accrue_zone_hold(order)
        order["fulfillment_status"] = "ZONE_CLEARED"
    elif action == "HOLD":
        order["fulfillment_status"] = "ZONE_HELD"
        order["zone_held_at"] = clock.now()
    elif action == "DECLINE":
        accrue_zone_hold(order)
        order["fulfillment_status"] = "DECLINED_OUT_OF_AREA"
        order["declined_reason"] = (
            "OUT_OF_AREA" if address["zone_state"] == "OUT_OF_ZONE" else "DRIVE_TIME_EXCEEDED"
        )
        order["settlement_status"] = "VOIDED"
    else:
        accrue_zone_hold(order)
        order["fulfillment_status"] = "CARRYOUT_REDIRECTED"
        order["declined_reason"] = "DRIVE_TIME_EXCEEDED"
        order["settlement_status"] = "VOIDED"
    db.touch(order)
    return response.ok(serialize.order(order))


@bp.post("/store-ops/orders/<order_id>/disclose-fee")
def disclose_fee(order_id):
    actor = auth.authenticate(["CustomerCareAgent", "Dispatcher"])
    (order,) = auth.guard(actor, [("order", order_id)])
    body = validate.body()
    disclosed_fee = validate.integer(body, "disclosed_fee_cents")
    disclosed_tip = validate.integer(body, "disclosed_tip_cents")
    notice_given = validate.boolean(body, "driver_tip_notice_given")
    if order["settlement_status"] != "UNDISCLOSED":
        fail("ERR_INVALID_ORDER_STATE", "Disclosure is declared only from UNDISCLOSED.")
    if order["fulfillment_status"] in ("DECLINED_OUT_OF_AREA", "CARRYOUT_REDIRECTED", "CLOSED"):
        fail("ERR_INVALID_ORDER_STATE", "This ticket can no longer be disclosed.")
    order["disclosed_fee_cents"] = disclosed_fee
    order["disclosed_tip_cents"] = disclosed_tip
    order["driver_tip_notice_given"] = notice_given
    order["fee_disclosure_accurate"] = bool(
        disclosed_fee == order["delivery_fee_cents"]
        and disclosed_tip == order["tip_cents"]
        and notice_given
    )
    order["fee_disclosed_at"] = clock.now()
    order["settlement_status"] = "DISCLOSED"
    db.touch(order)
    return response.ok(serialize.order(order))


@bp.post("/store-ops/orders/<order_id>/production")
def production(order_id):
    actor = auth.authenticate(["Dispatcher"])
    (order,) = auth.guard(actor, [("order", order_id)])
    body = validate.body()
    action = validate.enum(body, "action", ("START", "READY"))
    if action == "START":
        if order["fulfillment_status"] not in ("ZONE_CLEARED", "REMAKE_QUEUED"):
            fail("ERR_INVALID_ORDER_STATE", "Production starts from ZONE_CLEARED or REMAKE_QUEUED.")
        order["fulfillment_status"] = "IN_PRODUCTION"
    else:
        if order["fulfillment_status"] != "IN_PRODUCTION":
            fail("ERR_INVALID_ORDER_STATE", "READY is declared only from IN_PRODUCTION.")
        order["fulfillment_status"] = "READY"
        order["ready_at"] = clock.now()
    db.touch(order)
    return response.ok(serialize.order(order))


@bp.post("/store-ops/orders/<order_id>/remake")
def remake(order_id):
    actor = auth.authenticate(["StoreManager"])
    (order,) = auth.guard(actor, [("order", order_id)])
    body = validate.body()
    reason = validate.string(body, "reason")
    if order["fulfillment_status"] != "DELIVERED":
        fail("ERR_INVALID_ORDER_STATE", "A remake is queued only on a DELIVERED order.")
    if order["remake_count"] >= 1:
        fail("ERR_REMAKE_LIMIT_REACHED", "One remake per order.")
    if reason == "LATE":
        gross = order["order_to_door_gross_minutes"]
        threshold = order["promise_minutes_snapshot"] + REMAKE_GRACE_MINUTES
        if gross is None or not gross > threshold:
            fail("ERR_REMAKE_NOT_ELIGIBLE", "The order was inside its promise plus grace.")
    if order["door_arrival_at"] is not None:
        order["remake_hold_minutes"] = order["remake_hold_minutes"] + clock.elapsed_minutes_floor(
            clock.now(), order["door_arrival_at"]
        )
    order["door_arrival_at"] = None
    order["order_to_door_gross_minutes"] = None
    order["order_to_door_net_minutes"] = None
    order["remake_count"] = order["remake_count"] + 1
    order["remake_credit_cents"] = order["remake_credit_cents"] + order["food_subtotal_cents"]
    order["fulfillment_status"] = "REMAKE_QUEUED"
    if order["settlement_status"] in ("CHARGED", "ADJUSTED"):
        order["settlement_status"] = "ADJUSTED"
    delivered = [
        s
        for s in db.stops.values()
        if s["order_id"] == order["id"] and s["status"] == "DELIVERED"
    ]
    for stop in db.ordered(delivered):
        stop["status"] = "REMADE"
        db.touch(stop)
    db.touch(order)
    return response.ok(serialize.order(order))


@bp.get("/store-ops/orders/<order_id>")
def read_order(order_id):
    actor = auth.authenticate(READ_ROLES)
    (order,) = auth.guard(actor, [("order", order_id)])
    return response.ok(serialize.order(order))


@bp.get("/store-ops/orders")
def list_orders():
    actor = auth.authenticate(READ_ROLES)
    store_id = validate.filter_string("store_id")
    address_id = validate.filter_string("service_address_id")
    fulfillment_status = validate.filter_enum("fulfillment_status", FULFILMENT_STATUSES)
    settlement_status = validate.filter_enum("settlement_status", SETTLEMENT_STATUSES)
    records = list(db.orders.values())
    if actor.is_manager:
        records = [o for o in records if o["store_id"] == actor.user_id]
    if store_id is not None:
        records = [o for o in records if o["store_id"] == store_id]
    if address_id is not None:
        records = [o for o in records if o["service_address_id"] == address_id]
    if fulfillment_status is not None:
        records = [o for o in records if o["fulfillment_status"] == fulfillment_status]
    if settlement_status is not None:
        records = [o for o in records if o["settlement_status"] == settlement_status]
    return listing.respond(records, serialize.order)
