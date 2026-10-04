"""Service booking endpoints (PRD 3.5): posture, eligibility, overlap, duration, quota."""

from datetime import timedelta

from flask import Blueprint, request

from constants import (
    DAILY_SERVICE_MINUTES_CAP,
    DEPENDENT_DAILY_MINUTES_CAP,
    ROOM_BUFFER_MINUTES,
    SERVICE_TYPE_CAPACITY,
    SERVICE_TYPE_MAX_MINUTES,
    SERVICE_TYPES,
)
from guests import enforce_eligibility
from helpers import (
    authn,
    base_entity,
    body,
    err,
    get_booking,
    get_center,
    get_guest,
    now,
    paginate,
    req_datetime,
    req_enum,
    req_str,
    require_role,
    serialize,
    success_list,
    success_object,
    today,
    validation,
)
from storage import STORE

bp = Blueprint("bookings", __name__)

READ_ROLES = ("PlatformAdmin", "CenterManager", "Guest")


@bp.route("/centers/<cid>/service-bookings", methods=["POST"])
def create_booking(cid):
    uid, role = authn()
    require_role(role, ("CenterManager", "Guest"))
    b = body()
    # Entity-backed scope (PRD 2.1): a Guest books only for itself.
    if role == "Guest" and b.get("guest_id") is not None and b.get("guest_id") != uid:
        err("ERR_FORBIDDEN", 403, "A guest may book only for itself")

    guest_id = req_str(b, "guest_id")
    service_type = req_enum(b, "service_type", SERVICE_TYPES)
    start_at = req_datetime(b, "start_at")
    end_at = req_datetime(b, "end_at")
    if not end_at > start_at:
        validation("end_at must be later than start_at")
    if start_at < now():
        validation("start_at must not be in the past")
    minutes = int((end_at - start_at).total_seconds() // 60)
    if minutes <= 0:
        validation("booking length must be a positive number of whole minutes")

    center = get_center(cid)
    guest = get_guest(guest_id)

    # Posture gates (state class): CLOSED rejects all; RESTRICTED narrows services.
    if center["posture"] == "CLOSED":
        err("ERR_CENTER_CLOSED", 409, "Center posture is CLOSED")
    if center["posture"] == "RESTRICTED" and service_type in ("SLEEPING_AREA", "FAMILY_ROOM"):
        err("ERR_POSTURE_SERVICE_BLOCKED", 409, "Service not available while center is RESTRICTED")

    # Safety: guest eligibility with lazy expiry flip.
    enforce_eligibility(guest)

    # Temporal conflict (half-open; FAMILY_ROOM buffered) before capacity checks.
    pool = [
        bk for bk in STORE.bookings.values()
        if bk["center_id"] == center["id"]
        and bk["service_type"] == service_type
        and bk["status"] == "BOOKED"
    ]
    capacity = SERVICE_TYPE_CAPACITY[service_type]
    if service_type == "FAMILY_ROOM":
        buf = timedelta(minutes=ROOM_BUFFER_MINUTES)
        for bk in pool:
            if not (start_at >= bk["end_at"] + buf or end_at <= bk["start_at"] - buf):
                err("ERR_BOOKING_OVERLAP", 409, "Booking intersects the family room's buffered interval")
    else:
        # Max simultaneous pool occupancy inside the new window, plus the new one.
        points = set()
        for bk in pool:
            points.add(max(start_at, bk["start_at"]))
            points.add(min(end_at, bk["end_at"]))
        points.add(start_at)
        worst = 0
        for t in points:
            if t < start_at or t >= end_at:
                continue
            covering = sum(
                1 for bk in pool if bk["start_at"] <= t < bk["end_at"]
            )
            worst = max(worst, covering)
        if worst + 1 > capacity:
            err("ERR_BOOKING_OVERLAP", 409, "Booking would exceed the service type capacity")

    # Capacity/quota class: type duration ceiling, then daily quota.
    if minutes > SERVICE_TYPE_MAX_MINUTES[service_type]:
        err("ERR_BOOKING_DURATION_INVALID", 422, "Booking exceeds the service type duration limit")

    daily_cap = DEPENDENT_DAILY_MINUTES_CAP if guest["category"] == "DEPENDENT" else DAILY_SERVICE_MINUTES_CAP
    d = today()
    used = 0
    for bk in STORE.bookings.values():
        if bk["guest_id"] != guest["id"] or bk["status"] != "BOOKED":
            continue
        if bk["start_at"].date() != d:
            continue
        used += int((bk["end_at"] - bk["start_at"]).total_seconds() // 60)
    if minutes > (daily_cap - used):
        err("ERR_QUOTA_EXCEEDED", 409, "Booking exceeds the guest's remaining daily minutes")

    bk = base_entity()
    bk.update({
        "center_id": center["id"],
        "guest_id": guest["id"],
        "service_type": service_type,
        "start_at": start_at,
        "end_at": end_at,
        "status": "BOOKED",
    })
    STORE.bookings[bk["id"]] = bk
    return success_object(serialize(bk), status=201)


@bp.route("/service-bookings/<bid>", methods=["GET"])
def get_booking_route(bid):
    uid, role = authn()
    require_role(role, READ_ROLES)
    bk = get_booking(bid)
    if role == "Guest" and bk["guest_id"] != uid:
        err("ERR_FORBIDDEN", 403, "Guests may only view their own bookings")
    return success_object(serialize(bk))


@bp.route("/service-bookings", methods=["GET"])
def list_bookings():
    uid, role = authn()
    require_role(role, READ_ROLES)
    center_id = request.args.get("center_id")
    guest_id = request.args.get("guest_id")
    if role == "Guest":
        if guest_id is not None and guest_id != uid:
            err("ERR_FORBIDDEN", 403, "Guests are scoped to their own bookings")
        guest_id = uid
    items = list(STORE.bookings.values())
    if center_id is not None:
        items = [x for x in items if x["center_id"] == center_id]
    if guest_id is not None:
        items = [x for x in items if x["guest_id"] == guest_id]
    page, meta = paginate(items)
    return success_list(page, meta)
