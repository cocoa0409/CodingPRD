"""Booking routes."""

from datetime import timedelta

from flask import Blueprint, request

from db import DB
from common import base_resource, touch, paginate, parse_dt, dt_to_iso
from middleware import require_role
from errors import (not_found, invalid_state, zone_capacity, accessibility_zone,
                    hold_expired)
from response import success_object, success_list
import calc
import services

bp = Blueprint("bookings", __name__)


def booking_view(b):
    return dict(b)


@bp.post("/venue/shows/<sid>/bookings")
def create_booking(sid):
    require_role("Guest", "BoxOfficeAgent")
    s = DB.shows.get(sid)
    if not s:
        raise not_found()
    if s["status"] not in ("REHEARSAL", "CONFIRMED"):
        raise invalid_state("Show must be REHEARSAL or CONFIRMED")
    body = request.get_json(silent=True) or {}
    zone = body.get("zone")
    seats = int(body.get("seats", 1))
    seat_kind = body.get("seat_kind", "STANDARD")
    capacity = calc.ZONE_CAPACITY.get(zone)
    used = sum(
        b["seats"] for b in DB.bookings.values()
        if b["show_id"] == sid and b["zone"] == zone and b["status"] in ("HELD", "CONFIRMED")
    )
    if used + seats > capacity:
        raise zone_capacity()
    if seat_kind in ("WHEELCHAIR", "COMPANION") and zone == "APEX":
        raise accessibility_zone()
    prod = DB.productions.get(s["production_id"])
    prod = DB.productions.get(s["production_id"])
    unit, line, variant = calc.price_booking(prod, zone, seats)
    b = base_resource()
    b.update({
        "show_id": sid,
        "zone": zone,
        "seats": seats,
        "seat_kind": seat_kind,
        "unit_price_cents": unit,
        "line_total_cents": line,
        "quoted_variant": variant,
        "refund_cents": 0,
        "status": "HELD",
        "held_at": dt_to_iso(DB.clock),
    })
    DB.bookings[b["id"]] = b
    return success_object(booking_view(b), 201)


@bp.get("/venue/shows/<sid>/bookings")
def list_bookings(sid):
    require_role("BoxOfficeAgent", "VenueScheduler", "Guest")
    s = DB.shows.get(sid)
    if not s:
        raise not_found()
    items = sorted(
        [b for b in DB.bookings.values() if b["show_id"] == sid],
        key=lambda x: x["created_at"],
    )
    zone = request.args.get("zone")
    status = request.args.get("status")
    if zone:
        items = [b for b in items if b["zone"] == zone]
    if status:
        items = [b for b in items if b["status"] == status]
    page, limit, offset, total = paginate([booking_view(b) for b in items], request.args)
    return success_list(page, limit, offset, total)


@bp.get("/venue/shows/<sid>/settlement")
def get_settlement(sid):
    require_role("VenueScheduler", "ProductionDirector")
    s = DB.shows.get(sid)
    if not s:
        raise not_found()
    items = sorted(
        [x for x in DB.settlements.values() if x["show_id"] == sid],
        key=lambda x: x["created_at"],
    )
    page, limit, offset, total = paginate([dict(x) for x in items], request.args)
    return success_list(page, limit, offset, total)


@bp.get("/venue/bookings/<bid>")
def get_booking(bid):
    require_role("Guest", "BoxOfficeAgent")
    b = DB.bookings.get(bid)
    if not b:
        raise not_found()
    return success_object(booking_view(b))


@bp.post("/venue/bookings/<bid>/confirm")
def confirm_booking(bid):
    require_role("Guest", "BoxOfficeAgent")
    b = DB.bookings.get(bid)
    if not b:
        raise not_found()
    if b["status"] != "HELD":
        raise invalid_state()
    held_at = parse_dt(b["held_at"])
    if DB.clock >= held_at + timedelta(minutes=calc.HOLD_MINUTES):
        raise hold_expired()
    b["status"] = "CONFIRMED"
    touch(b)
    return success_object(booking_view(b))


@bp.post("/venue/bookings/<bid>/cancel")
def cancel_booking_route(bid):
    require_role("Guest", "BoxOfficeAgent")
    b = DB.bookings.get(bid)
    if not b:
        raise not_found()
    if b["status"] not in ("HELD", "CONFIRMED"):
        raise invalid_state()
    services.cancel_booking(b)
    return success_object(booking_view(b))
