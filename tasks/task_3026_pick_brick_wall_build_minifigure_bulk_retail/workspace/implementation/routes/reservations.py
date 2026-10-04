"""Mini-build registrations: joining, check-in and cancellation."""

from flask import Blueprint

from db import db, event_arrival, now
from errors import fail
from middleware import require, require_owner
from response import envelope, paginate
from services.core import get_event, get_member, get_reservation, new_record, touch
from services.events import (
    apply_standing_sanction,
    cancel_driven_promotion,
    recompute_event_counts,
    recompute_tier,
    within_event_window,
)
from utils import body, list_params, matches, out, require_fields

bp = Blueprint("reservations", __name__)


@bp.route("/stores/mini-build-reservations", methods=["POST"])
def register():
    require("StoreAssociate")
    payload = body()
    require_fields(payload, "store_event_id", "member_id")

    event = get_event(payload["store_event_id"])
    member = get_member(payload["member_id"])

    seats = int(payload.get("seats", 1))
    if seats < 1:
        fail("ERR_CONSTRAINT_VIOLATION", "seats must be at least 1.")

    # A request for more seats than the slot can hold could never be satisfied.
    if seats > event["capacity_units"]:
        fail("ERR_EVENT_CAPACITY_EXCEEDED",
             "The request exceeds the whole capacity of the slot.")

    if event["registered_count"] + seats <= event["capacity_units"]:
        status = "REGISTERED"
        event["registered_count"] += seats
    else:
        status = "WAITLISTED"
        event["waitlisted_count"] += 1

    arrival = event_arrival(event["store_id"]).next()
    reservation = new_record({
        "store_event_id": event["id"],
        "member_id": member["id"],
        "seats": seats,
        "wait_mark": event["waitlist_epoch"],
        "status": status,
        "arrival_counter": arrival,
        "checked_in_at_utc": None,
    })
    db().mini_build_reservations[reservation["id"]] = reservation
    recompute_event_counts(event)
    touch(event)
    return envelope(out(reservation), status=201)


@bp.route("/stores/mini-build-reservations", methods=["GET"])
def list_reservations():
    require("StoreAssociate", "Member")
    params = list_params()
    items = [r for r in db().mini_build_reservations.values()
             if matches(r, params, "store_event_id", "member_id", "status")]
    items.sort(key=lambda r: (r["created_at"], r["id"]))
    page, pagination = paginate(items, params)
    return envelope(out(page), response_type="array", pagination=pagination)


@bp.route("/stores/mini-build-reservations/<reservation_id>", methods=["GET"])
def read_reservation(reservation_id):
    require("StoreAssociate", "Member")
    return envelope(out(get_reservation(reservation_id)))


@bp.route("/stores/mini-build-reservations/<reservation_id>/check-in", methods=["POST"])
def check_in(reservation_id):
    reservation = get_reservation(reservation_id)
    require_owner(reservation["member_id"])
    require("Member")

    if reservation["status"] not in ("REGISTERED", "PROMOTED"):
        fail("ERR_INVALID_STATE", "Only a registered or promoted place may check in.")

    event = get_event(reservation["store_event_id"])
    if event["stage"] != "OPEN" or not within_event_window(event):
        fail("ERR_EVENT_WINDOW_CLOSED",
             "The logical clock is outside the event window.")

    reservation["status"] = "PASSED"
    reservation["checked_in_at_utc"] = now()
    touch(reservation)
    recompute_event_counts(event)
    touch(event)

    member = get_member(reservation["member_id"])
    member["passed_mb_reservations"] += 1
    touch(member)
    recompute_tier(member)
    if member["tier"] == "VIP":
        from services.launch import reclass_waiting_rows
        reclass_waiting_rows(member)
    apply_standing_sanction(member)
    return envelope(out(reservation))


@bp.route("/stores/mini-build-reservations/<reservation_id>/cancel", methods=["POST"])
def cancel(reservation_id):
    reservation = get_reservation(reservation_id)
    require_owner(reservation["member_id"])
    require("Member")

    if reservation["status"] not in ("REGISTERED", "WAITLISTED", "PROMOTED"):
        fail("ERR_INVALID_STATE", "This reservation is already in a terminal state.")

    event = get_event(reservation["store_event_id"])
    held_seat = reservation["status"] in ("REGISTERED", "PROMOTED")
    mark = event["waitlist_epoch"]
    reservation["status"] = "EXPIRED"
    touch(reservation)

    # The cancelled seat is free for the next waitlisted guest, so the seat
    # count the promotion pass measures against must be re-derived after the
    # cancellation -- the row that held it is already EXPIRED.
    recompute_event_counts(event)

    current = now()
    if event["stage"] == "CLOSED" and current < event["end_utc"]:
        if event["registered_count"] + reservation["seats"] <= event["capacity_units"]:
            event["stage"] = "OPEN"
            touch(event)

    if held_seat:
        cancel_driven_promotion(event, mark)

    recompute_event_counts(event)
    touch(event)
    return envelope(out(reservation))