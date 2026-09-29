"""Site-access crew bookings (PRD section 3.8, final paragraphs).

Crew capacity is an aggregate constraint over every BOOKED or COMPLETED
booking on the parcel whose half-open window intersects the requested one, and
it is tested at rung 39 — above the window-in-past rule at rung 40.
"""

from flask import Blueprint

import access
import calc
import cascades
import serializers as ser
import validation as v
from auth import LAND_AGENT, PORTFOLIO_MANAGER, TITLE_COUNSEL, require
from envelope import ok, ok_list
from errors import (
    ERR_CREW_CAPACITY_EXCEEDED,
    ERR_INVALID_STATE,
    ERR_INVALID_WINDOW_RANGE,
    ERR_WINDOW_IN_PAST,
    fail,
)
from store import db, insert, now, ordered, touch

bp = Blueprint("bookings", __name__, url_prefix="/land-origination")

PURPOSES = ("TITLE_SURVEY", "GEOTECH", "ENV_SURVEY", "CONSTRUCTION_STAGING")
READERS = (LAND_AGENT, TITLE_COUNSEL, PORTFOLIO_MANAGER)
WRITERS = (LAND_AGENT, TITLE_COUNSEL)
OCCUPYING = ("BOOKED", "COMPLETED")


@bp.get("/site-access-bookings/<booking_id>")
@require(*READERS)
def get_booking(booking_id):
    return ok(ser.booking(access.booking(booking_id)))


@bp.get("/site-access-bookings")
@require(*READERS)
def list_bookings():
    limit, offset = v.pagination()
    rows = ordered(db.bookings.values())
    rows = v.apply_filters(rows, [
        ("parcel_id", v.query_str("parcel_id")),
        ("status", v.query_str("status")),
    ])
    page, total = v.paginate(rows, limit, offset)
    return ok_list(ser.many(ser.booking, page), limit, offset, total)


def _occupied_crews(parcel_id, window_start, window_end):
    """Cancelled bookings are excluded; abutting windows never intersect."""
    total = 0
    for other in cascades.parcel_bookings(parcel_id):
        if other["status"] not in OCCUPYING:
            continue
        if window_start < other["window_end"] \
                and window_end > other["window_start"]:
            total += int(other["crew_count"])
    return total


@bp.post("/site-access-bookings")
@require(*WRITERS)
def create_booking():
    body = v.json_body()
    # Rung 4 resolves ahead of the rung-14 shape pass.
    parcel_id = v.lookup_fk(body, "parcel_id")
    parcel = access.parcel(parcel_id) if parcel_id else None

    v.req_fk(body, "parcel_id")
    purpose = v.req_enum(body, "purpose", PURPOSES)
    window_start = v.req_dt(body, "window_start")
    window_end = v.req_dt(body, "window_end")
    crew_count = v.req_int(body, "crew_count", lo=1,
                           hi=calc.PARCEL_MAX_CONCURRENT_CREWS)

    if window_end <= window_start:
        fail(ERR_INVALID_WINDOW_RANGE)
    occupied = _occupied_crews(parcel["id"], window_start, window_end)
    if occupied + crew_count > calc.PARCEL_MAX_CONCURRENT_CREWS:
        fail(ERR_CREW_CAPACITY_EXCEEDED)
    # A booking starting at exactly the current instant is admissible.
    if window_start < now():
        fail(ERR_WINDOW_IN_PAST)

    row = insert("bookings", {
        "parcel_id": parcel["id"],
        "purpose": purpose,
        "window_start": window_start,
        "window_end": window_end,
        "crew_count": crew_count,
        "cancelled_at": None,
        "status": "BOOKED",
    })
    return ok(ser.booking(row), 201)


@bp.post("/site-access-bookings/<booking_id>/cancel")
@require(*WRITERS)
def cancel_booking(booking_id):
    row = access.booking(booking_id)
    if row["status"] != "BOOKED":
        fail(ERR_INVALID_STATE)
    row["status"] = "CANCELLED"
    row["cancelled_at"] = now()
    touch(row)
    return ok(ser.booking(row))
