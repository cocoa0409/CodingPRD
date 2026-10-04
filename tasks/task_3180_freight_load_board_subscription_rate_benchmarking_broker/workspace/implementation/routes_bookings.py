from flask import Blueprint, request

from db import db
from middleware import get_context, require_role
from response import APIError, success
from services import (
    check_org_active,
    check_safety_gate,
    get_booking,
    get_carrier,
    get_load,
    get_truck,
    lazy_expire_load,
    lazy_expire_truck,
    new_resource,
    paginate,
    parse_limit_offset,
    recompute_contribution_flag,
    require_active_subscription,
    require_fields,
    require_positive_int,
    sorted_by_created,
    touch,
)
from util import iso_ms

bp = Blueprint("bookings", __name__)

READ_ROLES = ("PlatformAdmin", "ComplianceAnalyst", "DataOps", "BrokerAdmin", "CarrierAdmin")


@bp.post("/bookings")
def create_booking():
    user_id, role = get_context()
    require_role(role, ("CarrierAdmin",))
    body = request.get_json(silent=True) or {}
    require_fields(body, ["load_post_id", "truck_post_id", "agreed_rate_cents"])
    load = get_load(db, body["load_post_id"])
    truck = get_truck(db, body["truck_post_id"])
    carrier = get_carrier(db, user_id)
    check_org_active(carrier)
    require_active_subscription(db, carrier_org_id=carrier["id"])
    check_safety_gate(db, carrier_org_id=carrier["id"])
    broker = db.broker_orgs.get(load["broker_org_id"])
    if broker is not None:
        check_org_active(broker)
        check_safety_gate(db, broker_org_id=broker["id"])
    lazy_expire_load(db, load)
    lazy_expire_truck(db, truck)
    if load["status"] != "OPEN" or load["visibility"] != "LISTED":
        raise APIError("ERR_LOAD_POST_NOT_OPEN", 409, "Load post is not OPEN and LISTED")
    if truck["status"] != "AVAILABLE":
        raise APIError("ERR_TRUCK_POST_NOT_AVAILABLE", 409, "Truck post is not AVAILABLE")
    if truck["carrier_org_id"] != carrier["id"]:
        raise APIError("ERR_NOT_RESOURCE_OWNER", 403, "Acting carrier does not own this truck post")
    require_positive_int(body["agreed_rate_cents"], "agreed_rate_cents")
    booking = new_resource(db, {
        "load_post_id": load["id"],
        "truck_post_id": truck["id"],
        "agreed_rate_cents": body["agreed_rate_cents"],
        "status": "BOOKED",
        "rate_transaction_id": None,
    })
    db.bookings[booking["id"]] = booking
    load["status"] = "BOOKED"
    touch(db, load)
    truck["status"] = "BOOKED"
    touch(db, truck)
    return success(booking, 201)


@bp.get("/bookings")
def list_bookings():
    _, role = get_context()
    require_role(role, READ_ROLES)
    limit, offset = parse_limit_offset()
    items = list(db.bookings.values())
    for f in ("load_post_id", "truck_post_id", "rate_transaction_id", "status"):
        v = request.args.get(f)
        if v is not None:
            items = [b for b in items if b.get(f) == v]
    items = sorted_by_created(items)
    page, meta = paginate(items, limit, offset)
    return success(page, 200, meta)


@bp.get("/bookings/<booking_id>")
def get_booking_route(booking_id):
    _, role = get_context()
    require_role(role, READ_ROLES)
    return success(get_booking(db, booking_id))


@bp.post("/bookings/<booking_id>/complete")
def complete_booking(booking_id):
    user_id, role = get_context()
    require_role(role, ("CarrierAdmin",))
    booking = get_booking(db, booking_id)
    carrier = get_carrier(db, user_id)
    if booking["status"] != "BOOKED":
        raise APIError("ERR_BOOKING_NOT_ACTIVE", 409, "Booking is not BOOKED")
    truck = get_truck(db, booking["truck_post_id"])
    if truck["carrier_org_id"] != carrier["id"]:
        raise APIError("ERR_NOT_RESOURCE_OWNER", 403, "Acting carrier does not own the truck on this booking")
    load = get_load(db, booking["load_post_id"])
    booking["status"] = "COMPLETED"
    touch(db, booking)
    load["status"] = "COMPLETED"
    touch(db, load)
    truck["status"] = "COMPLETED"
    touch(db, truck)
    txn = new_resource(db, {
        "source": "BOOKING",
        "booking_id": booking["id"],
        "reporter_broker_org_id": None,
        "reporter_carrier_org_id": carrier["id"],
        "origin": load["origin"],
        "destination": load["destination"],
        "equipment_type": load["equipment_type"],
        "rate_kind": "SPOT",
        "rate_cents": booking["agreed_rate_cents"],
        "fuel_price_cents": None,
        "transaction_date": iso_ms(db.clock),
        "status": "ACCEPTED",
    })
    db.rate_transactions[txn["id"]] = txn
    booking["rate_transaction_id"] = txn["id"]
    touch(db, booking)
    recompute_contribution_flag(db, carrier, is_broker=False)
    return success(booking)


@bp.post("/bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    user_id, role = get_context()
    require_role(role, ("CarrierAdmin", "BrokerAdmin"))
    booking = get_booking(db, booking_id)
    if booking["status"] != "BOOKED":
        raise APIError("ERR_BOOKING_NOT_ACTIVE", 409, "Booking is not BOOKED")
    load = get_load(db, booking["load_post_id"])
    truck = get_truck(db, booking["truck_post_id"])
    if role == "CarrierAdmin":
        carrier = get_carrier(db, user_id)
        if truck["carrier_org_id"] != carrier["id"]:
            raise APIError("ERR_NOT_RESOURCE_OWNER", 403, "Acting carrier does not own the truck on this booking")
    else:
        broker = db.broker_orgs.get(user_id)
        if broker is None or load["broker_org_id"] != broker["id"]:
            raise APIError("ERR_NOT_RESOURCE_OWNER", 403, "Acting broker does not own the load on this booking")
    booking["status"] = "CANCELLED"
    touch(db, booking)
    load["status"] = "OPEN"
    load["visibility"] = "LISTED"
    touch(db, load)
    truck["status"] = "AVAILABLE"
    touch(db, truck)
    return success(booking)
