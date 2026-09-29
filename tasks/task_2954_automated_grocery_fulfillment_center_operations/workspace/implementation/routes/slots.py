"""Delivery slots and their capacity levers, shopper accounts, and slot
bookings with the waitlist (PRD 3.1, 3.3)."""

from flask import Blueprint

import db as store
from db import db
from errors import ApiError
import response as resp
import validation as v
from middleware import endpoint, must_get, require_ownership
from services import derive, money, selectors

bp = Blueprint("slots", __name__)

ADMIN = ["FulfillmentAdmin"]
SLOT_READERS = ["FulfillmentAdmin", "WavePlanner", "PickOperator", "Customer"]
ACCOUNT_READERS = ["FulfillmentAdmin", "WavePlanner", "Customer"]
BOOKING_READERS = ["FulfillmentAdmin", "WavePlanner", "Customer"]
CUSTOMER = ["Customer"]
LOYALTY_TIERS = ("BASIC", "PLUS", "PREMIER")


# --------------------------------------------------------------------------
# Delivery slots
# --------------------------------------------------------------------------
@bp.route("/delivery-slots", methods=["POST"])
@endpoint(roles=ADMIN, mutating=True)
def create_slot():
    body = v.read_body()
    route = v.fk(body, "route_id", db.routes, "ERR_ROUTE_NOT_FOUND")
    data = v.check_body(body, [
        v.f_id("route_id"),
        v.f_instant("window_start"),
        v.f_instant("window_end"),
        v.f_int("total_capacity_units", 1, 5000),
        v.f_int("withheld_units", 0, None, required=False, default=0),
    ])
    if data["window_end"] <= data["window_start"]:
        v.bad("window_end must be strictly after window_start")
    if data["withheld_units"] > data["total_capacity_units"]:
        v.bad("withheld_units may not exceed total_capacity_units")
    slot = store.insert(db.slots, {
        "route_id": route["id"],
        "window_start": data["window_start"],
        "window_end": data["window_end"],
        "total_capacity_units": data["total_capacity_units"],
        "withheld_units": data["withheld_units"],
        "held_units": 0,
        "confirmed_units": 0,
        "available_units": 0,
        "surge_multiplier": store.SURGE_FLOOR,
    })
    derive.recompute_slot_ledger(slot)
    money.recompute_surge(slot)
    return resp.created(slot)


@bp.route("/delivery-slots/<slot_id>", methods=["GET"])
@endpoint(roles=SLOT_READERS)
def read_slot(slot_id):
    return resp.obj(must_get(db.slots, slot_id, "ERR_SLOT_NOT_FOUND"))


@bp.route("/delivery-slots", methods=["GET"])
@endpoint(roles=SLOT_READERS)
def list_slots():
    items = resp.filtered(list(db.slots.values()), {"route_id": "route_id"})
    return resp.listing(items)


@bp.route("/delivery-slots/<slot_id>/release-capacity", methods=["POST"])
@endpoint(roles=ADMIN, mutating=True)
def release_capacity(slot_id):
    slot = must_get(db.slots, slot_id, "ERR_SLOT_NOT_FOUND")
    data = v.check_body(v.read_body(), [v.f_int("units", 0, None)])
    if data["units"] > slot["withheld_units"]:
        raise ApiError(
            "ERR_WITHHELD_UNITS_EXCEEDED",
            "cannot release more units than are currently withheld",
        )
    slot["withheld_units"] = slot["withheld_units"] - data["units"]
    derive.recompute_slot_ledger(slot)
    selectors.promote_one_waitlisted(slot)
    derive.recompute_slot_ledger(slot)
    money.recompute_surge(slot)
    return resp.obj(slot)


@bp.route("/delivery-slots/<slot_id>/withhold-capacity", methods=["POST"])
@endpoint(roles=ADMIN, mutating=True)
def withhold_capacity(slot_id):
    slot = must_get(db.slots, slot_id, "ERR_SLOT_NOT_FOUND")
    data = v.check_body(v.read_body(), [v.f_int("units", 0, None)])
    headroom = slot["total_capacity_units"] - slot["withheld_units"]
    if data["units"] > headroom:
        raise ApiError(
            "ERR_WITHHELD_UNITS_EXCEEDED",
            "withholding may not push the total withheld above capacity",
        )
    slot["withheld_units"] = slot["withheld_units"] + data["units"]
    derive.recompute_slot_ledger(slot)
    selectors.bump_confirmed_bookings(slot)
    derive.recompute_slot_ledger(slot)
    money.recompute_surge(slot)
    return resp.obj(slot)


# --------------------------------------------------------------------------
# Customer accounts
# --------------------------------------------------------------------------
@bp.route("/customer-accounts", methods=["POST"])
@endpoint(roles=ADMIN, mutating=True)
def create_account():
    body = v.read_body()
    route = v.fk(body, "home_route_id", db.routes, "ERR_ROUTE_NOT_FOUND")
    data = v.check_body(body, [
        v.f_email("email"),
        v.f_str("full_name", 1, 120),
        v.f_enum("loyalty_tier", LOYALTY_TIERS, required=False, default="BASIC"),
        v.f_id("home_route_id"),
    ])
    v.ensure_unique(db.accounts, "email", data["email"])
    account = store.insert(db.accounts, {
        "email": data["email"],
        "full_name": data["full_name"],
        "loyalty_tier": data["loyalty_tier"],
        "home_route_id": route["id"],
    })
    return resp.created(account)


@bp.route("/customer-accounts/<account_id>", methods=["GET"])
@endpoint(roles=ACCOUNT_READERS)
def read_account(account_id):
    return resp.obj(
        must_get(db.accounts, account_id, "ERR_CUSTOMER_ACCOUNT_NOT_FOUND")
    )


@bp.route("/customer-accounts", methods=["GET"])
@endpoint(roles=["FulfillmentAdmin", "WavePlanner"])
def list_accounts():
    items = resp.filtered(list(db.accounts.values()), {
        "home_route_id": "home_route_id",
        "loyalty_tier": "loyalty_tier",
    })
    return resp.listing(items)


# --------------------------------------------------------------------------
# Slot bookings
# --------------------------------------------------------------------------
@bp.route("/slot-bookings", methods=["POST"])
@endpoint(roles=CUSTOMER, mutating=True)
def create_booking():
    body = v.read_body()
    # gate 6 -- body foreign keys, in declared field order
    slot = v.fk(body, "delivery_slot_id", db.slots, "ERR_SLOT_NOT_FOUND")
    order = v.fk(body, "customer_order_id", db.orders, "ERR_ORDER_NOT_FOUND")
    # gate 7 -- ownership
    if order is not None:
        require_ownership(order)
    # gate 8 -- shape
    data = v.check_body(body, [
        v.f_id("delivery_slot_id"),
        v.f_id("customer_order_id"),
        v.f_int("units", 1, 500),
        v.f_int("expected_order_version", 0, None),
    ])
    # gate 10 -- optimistic concurrency
    if data["expected_order_version"] != order["version"]:
        raise ApiError("ERR_STALE_VERSION", "the order has been modified since it was read")
    # gate 18 -- home route
    account = db.accounts[order["customer_id"]]
    if slot["route_id"] != account["home_route_id"]:
        raise ApiError("ERR_ROUTE_MISMATCH", "the slot does not serve the shopper's home route")
    # gate 24 -- booking window still open
    if db.clock >= slot["window_start"]:
        raise ApiError("ERR_SLOT_WINDOW_CLOSED", "the slot's booking window has closed")
    # gate 30 -- single live booking per order
    for existing in derive.order_bookings(order):
        if existing["status"] in derive.LIVE_BOOKING_STATUSES:
            raise ApiError(
                "ERR_DUPLICATE_SLOT_BOOKING", "the order already holds a live booking"
            )
    # gate 32 -- the booking could never be satisfied
    if data["units"] > slot["total_capacity_units"] - slot["withheld_units"]:
        raise ApiError(
            "ERR_SLOT_UNITS_EXCEED_CAPACITY",
            "the requested units exceed the slot's sellable capacity",
        )
    # gate 33 -- minimum basket value
    if order["merchandise_subtotal_cents"] < store.MINIMUM_ORDER_CENTS:
        raise ApiError(
            "ERR_MINIMUM_ORDER_NOT_MET", "the basket is below the ten dollar minimum"
        )

    route = db.routes[slot["route_id"]]
    multiplier = slot["surge_multiplier"]
    status = "HELD" if slot["available_units"] >= data["units"] else "WAITLISTED"
    booking = store.insert(db.bookings, {
        "delivery_slot_id": slot["id"],
        "customer_order_id": order["id"],
        "units": data["units"],
        "status": status,
        "surge_multiplier_at_booking": multiplier,
        "quoted_fee_cents": money.quoted_fee(route, multiplier),
    })
    derive.recompute_slot_ledger(slot)
    money.recompute_surge(slot)
    money.run_waterfall(order)
    store.bump(order)
    return resp.created(booking)


@bp.route("/slot-bookings/<booking_id>", methods=["GET"])
@endpoint(roles=BOOKING_READERS)
def read_booking(booking_id):
    # PRD 2.8 gate 7 applies to exactly seven POST operations, so a read is
    # deliberately not ownership-gated.
    return resp.obj(must_get(db.bookings, booking_id, "ERR_BOOKING_NOT_FOUND"))


@bp.route("/slot-bookings", methods=["GET"])
@endpoint(roles=BOOKING_READERS)
def list_bookings():
    items = resp.filtered(list(db.bookings.values()), {
        "delivery_slot_id": "delivery_slot_id",
        "customer_order_id": "customer_order_id",
        "status": "status",
    })
    return resp.listing(items)


@bp.route("/slot-bookings/<booking_id>/confirm", methods=["POST"])
@endpoint(roles=CUSTOMER, mutating=True)
def confirm_booking(booking_id):
    booking = must_get(db.bookings, booking_id, "ERR_BOOKING_NOT_FOUND")
    order = db.orders[booking["customer_order_id"]]
    require_ownership(order)
    v.check_body(v.read_body(), [])
    slot = db.slots[booking["delivery_slot_id"]]
    # gate 11
    if booking["status"] != "HELD":
        raise ApiError("ERR_INVALID_STATE", "only a HELD booking can be confirmed")
    # gate 24
    if db.clock >= slot["window_start"]:
        raise ApiError("ERR_SLOT_WINDOW_CLOSED", "the slot's booking window has closed")
    # minimum basket value still applies at confirmation (PRD 3.3)
    if order["merchandise_subtotal_cents"] < store.MINIMUM_ORDER_CENTS:
        raise ApiError(
            "ERR_MINIMUM_ORDER_NOT_MET", "the basket is below the ten dollar minimum"
        )

    booking["status"] = "CONFIRMED"
    derive.recompute_slot_ledger(slot)
    money.recompute_surge(slot)
    if order["fulfillment_status"] == "DRAFT":
        order["fulfillment_status"] = "SLOTTED"
    money.run_waterfall(order)
    money.authorize(order)
    store.bump(order)
    return resp.obj(booking)
