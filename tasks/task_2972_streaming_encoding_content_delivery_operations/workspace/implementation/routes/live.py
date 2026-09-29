"""Live-event capacity reservations, arming, failover and release (PRD 3.8)."""

from flask import Blueprint

from db import db, dec, new_row, now, q2, rows, sort_rows, touch
from errors import ApiError
from middleware import endpoint
from response import created, ok, read_page_params
from routes.common import (
    RESERVATION_STATES, apply_filters, get_reservation, get_title, get_vendor,
    send_list,
)
from services import calc
from services.domain import refresh_vendor_reserved
from validation import S, parse_body, parse_query

bp = Blueprint("live", __name__)

RESERVATION_CREATE = [
    S("title_id", "string"),
    S("primary_vendor_id", "string"),
    S("failover_vendor_id", "string", required=False, default=None, nullable=True),
    S("window_start_at", "instant"),
    S("window_end_at", "instant"),
    S("reserved_gbps", "number", exclusive_minimum=0, scale=2),
    S("buffer_minutes", "integer", required=False, default=15, minimum=0, maximum=60),
]


def _capacity_ok(vendor, start, end, buffer_minutes, gbps, exclude_id=None):
    held = calc.capacity_held_against(vendor["id"], start, end, buffer_minutes, exclude_id)
    return q2(held + dec(gbps)) <= dec(vendor["committed_gbps"])


def _covered_by_single_window(title_id, start, end):
    for window in calc.title_windows(title_id):
        if window["state"] not in ("SCHEDULED", "ACTIVE"):
            continue
        if window["window_start_at"] <= start and end <= window["window_end_at"]:
            return True
    return False


@bp.post("/live-reservations")
@endpoint(["DeliveryEngineer"])
def create_reservation():
    payload = parse_body(RESERVATION_CREATE)
    title = get_title(payload["title_id"])
    primary = get_vendor(payload["primary_vendor_id"])
    failover_id = payload.get("failover_vendor_id")
    if failover_id is not None:
        get_vendor(failover_id)
    if title["content_type"] != "LIVE_EVENT":
        raise ApiError("ERR_NOT_LIVE_EVENT_TITLE")
    if failover_id is not None and failover_id == primary["id"]:
        raise ApiError("ERR_FAILOVER_SAME_AS_PRIMARY")
    start = payload["window_start_at"]
    end = payload["window_end_at"]
    if not start < end:
        raise ApiError("ERR_WINDOW_BOUNDS_INVALID")
    if start < now():
        raise ApiError("ERR_WINDOW_IN_PAST")
    if not _covered_by_single_window(title["id"], start, end):
        raise ApiError("ERR_RESERVATION_OUTSIDE_LICENSE")
    buffer_minutes = payload["buffer_minutes"]
    gbps = q2(payload["reserved_gbps"])
    if not _capacity_ok(primary, start, end, buffer_minutes, gbps):
        raise ApiError("ERR_VENDOR_CAPACITY_EXCEEDED")
    reservation = new_row()
    reservation["title_id"] = title["id"]
    reservation["primary_vendor_id"] = primary["id"]
    reservation["failover_vendor_id"] = failover_id
    reservation["active_vendor_id"] = primary["id"]
    reservation["window_start_at"] = start
    reservation["window_end_at"] = end
    reservation["reserved_gbps"] = gbps
    reservation["buffer_minutes"] = buffer_minutes
    reservation["state"] = "RESERVED"
    reservation["failover_at"] = None
    reservation["released_gbps"] = q2(0)
    db.reservations[reservation["id"]] = reservation
    refresh_vendor_reserved(primary)
    return created(reservation)


@bp.get("/live-reservations/<reservation_id>")
@endpoint(["DeliveryEngineer", "ContentOps", "PlatformAdmin"])
def read_reservation(reservation_id):
    parse_query([], allow_paging=False)
    return ok(get_reservation(reservation_id))


@bp.get("/live-reservations")
@endpoint(["DeliveryEngineer", "ContentOps", "PlatformAdmin", "VendorOperator"],
          scope="reservations_list")
def list_reservations():
    filters = parse_query([
        S("title_id", "string"),
        S("primary_vendor_id", "string"),
        S("failover_vendor_id", "string"),
        S("active_vendor_id", "string"),
        S("state", "enum", values=RESERVATION_STATES),
    ])
    page, page_size = read_page_params()
    items = apply_filters(rows(db.reservations), filters, {})
    ordered = sort_rows(items, [
        (lambda r: r["window_start_at"], False),
        (lambda r: r["created_at"], False),
    ])
    return send_list(ordered, page, page_size)


@bp.post("/live-reservations/<reservation_id>/arm")
@endpoint(["DeliveryEngineer"])
def arm_reservation(reservation_id):
    parse_body([])
    reservation = get_reservation(reservation_id)
    if reservation["state"] != "RESERVED":
        raise ApiError("ERR_RESERVATION_STATE_INVALID")
    if not now() < reservation["window_end_at"]:
        # A broadcast whose window has already elapsed can no longer be armed.
        raise ApiError("ERR_RESERVATION_STATE_INVALID")
    title = db.titles[reservation["title_id"]]
    if not any(p["state"] == "PACKAGED" for p in calc.title_packages(title["id"])):
        raise ApiError("ERR_PACKAGE_NOT_READY")
    routable = [
        p
        for p in rows(db.policies)
        if p["title_id"] == title["id"] and p["state"] in ("ACTIVE", "STANDBY_ONLY")
    ]
    if not routable:
        raise ApiError("ERR_PACKAGE_NOT_READY", "the title has no routable steering policy")
    reservation["state"] = "ARMED"
    touch(reservation)
    return ok(reservation)


@bp.post("/live-reservations/<reservation_id>/failover")
@endpoint(["DeliveryEngineer"])
def failover_reservation(reservation_id):
    parse_body([])
    reservation = get_reservation(reservation_id)
    if reservation["state"] not in ("ARMED", "LIVE"):
        raise ApiError("ERR_RESERVATION_STATE_INVALID")
    target_id = reservation["failover_vendor_id"]
    target = db.vendors.get(target_id) if target_id else None
    if target is None or target["state"] == "DRAINED":
        raise ApiError("ERR_VENDOR_CAPACITY_EXCEEDED")
    if not _capacity_ok(
        target, reservation["window_start_at"], reservation["window_end_at"],
        reservation["buffer_minutes"], reservation["reserved_gbps"], reservation["id"],
    ):
        raise ApiError("ERR_VENDOR_CAPACITY_EXCEEDED")
    outgoing = db.vendors.get(reservation["active_vendor_id"])
    reservation["active_vendor_id"] = target["id"]
    reservation["failover_at"] = now()
    reservation["state"] = "FAILED_OVER"
    touch(reservation)
    # The compensating pair: the outgoing vendor is debited and the incoming
    # vendor credited by exactly the same figure.
    if outgoing is not None:
        refresh_vendor_reserved(outgoing)
    refresh_vendor_reserved(target)
    return ok(reservation)


@bp.post("/live-reservations/<reservation_id>/cancel")
@endpoint(["DeliveryEngineer"])
def cancel_reservation(reservation_id):
    parse_body([])
    reservation = get_reservation(reservation_id)
    if reservation["state"] not in ("RESERVED", "ARMED"):
        raise ApiError("ERR_RESERVATION_STATE_INVALID")
    carrier = db.vendors.get(reservation["active_vendor_id"])
    reservation["state"] = "CANCELLED"
    reservation["released_gbps"] = q2(reservation["reserved_gbps"])
    touch(reservation)
    if carrier is not None:
        refresh_vendor_reserved(carrier)
    return ok(reservation)
