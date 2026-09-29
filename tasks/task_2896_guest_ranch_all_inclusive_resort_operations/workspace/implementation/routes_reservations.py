"""Seats on a slot, the mounts they hold and the ride itself (PRD 3.8)."""

from flask import Blueprint

import calc
import derive
import fields
from auth import ALL_OPERATIONAL, EVERYONE, auth
from derive import Touch, reservation_json
from envelope import created, listing, ok
from errors import ApiError
from fields import body, require
from lookup import find, find_body_ref
from store import db

bp = Blueprint("reservations", __name__)

RESERVATION_STATUSES = ("CONFIRMED", "CHECKED_IN", "COMPLETED", "NO_SHOW", "CANCELLED")
MOUNT_STATUSES = ("NOT_REQUIRED", "PENDING", "ASSIGNED", "RELEASED", "COMPLETED")


def _slot_of(seat):
    return db.activity_slots.get(seat["slot_id"])


@bp.post("/activity-slots/<slot_id>/reservations")
def create_reservation(slot_id):
    auth("ReservationsAgent")
    slot = find("activity_slots", slot_id)
    data = body()
    booking = find_body_ref("bookings", data, "booking_id")
    guest = find_body_ref("guests", data, "guest_id")
    require(data, "booking_id", "guest_id", "expected_slot_version")
    fields.as_str(data, "booking_id")
    fields.as_str(data, "guest_id")
    pin = fields.as_int(data, "expected_slot_version")
    if booking is None:
        booking = find("bookings", data["booking_id"])
    if guest is None:
        guest = find("guests", data["guest_id"])

    roster = [m["guest_id"] for m in booking["party_members"]]
    if booking["season_id"] != slot["season_id"] or guest["id"] not in roster:
        raise ApiError(
            "ERR_SEASON_MISMATCH",
            "The booking must share the slot's season and carry this guest.",
        )
    if pin != int(slot["version"]):
        raise ApiError(
            "ERR_STALE_SLOT_VERSION",
            "The supplied expected_slot_version is out of date.",
        )
    if slot["slot_status"] not in derive.OPENABLE_SLOT_STATUSES:
        raise ApiError(
            "ERR_SLOT_STATE_INVALID",
            "A %s slot cannot take a seat." % slot["slot_status"],
        )
    if guest["guest_standing"] == "SUSPENDED":
        raise ApiError("ERR_GUEST_SUSPENDED", "The guest is suspended.")
    if derive.waiver_status(guest) != "SIGNED":
        raise ApiError(
            "ERR_WAIVER_NOT_SIGNED", "The guest holds no live liability waiver."
        )
    if slot["mount_required"] and guest.get("equine_statute_ack") is not True:
        raise ApiError(
            "ERR_EQUINE_STATUTE_ACK_REQUIRED",
            "A mounted slot requires the equine-activity acknowledgement.",
        )
    rider_rank = derive.effective_rank(guest)
    if calc.RANKS[rider_rank] < calc.RANKS[slot["min_ability_rank"]]:
        raise ApiError(
            "ERR_RIDER_ABILITY_INSUFFICIENT",
            "The rider's effective rank is below the slot's minimum.",
        )
    for seat in derive.seats_of_guest(guest["id"]):
        if seat["reservation_status"] not in derive.LIVE_SEAT_STATUSES:
            continue
        other = _slot_of(seat)
        if other is None or other["id"] == slot["id"]:
            continue
        if calc.intervals_overlap(
            slot["starts_at"], slot["ends_at"], other["starts_at"], other["ends_at"]
        ):
            raise ApiError(
                "ERR_GUEST_SLOT_CONFLICT",
                "The guest already holds a seat on an overlapping slot.",
            )
    if slot["slot_status"] == "HOLD":
        raise ApiError("ERR_SLOT_ON_HOLD", "The slot is on HOLD.")
    if derive.slot_state(slot)["seats_available"] < 1:
        raise ApiError("ERR_SLOT_FULL", "The slot has no seat left.")
    for seat in derive.seats_of_slot(slot["id"]):
        if (
            seat["guest_id"] == guest["id"]
            and seat["reservation_status"] in derive.LIVE_SEAT_STATUSES
        ):
            raise ApiError(
                "ERR_DUPLICATE_RESERVATION",
                "The guest already holds a live seat on this slot.",
            )

    surcharge = int(slot["rider_surcharge_cents"])
    row = db.insert(
        "activity_reservations",
        {
            "slot_id": slot["id"],
            "booking_id": booking["id"],
            "guest_id": guest["id"],
            "assigned_horse_id": None,
            "reservation_status": "CONFIRMED",
            "mount_status": "PENDING" if slot["mount_required"] else "NOT_REQUIRED",
            "surcharge_cents": surcharge,
            "surcharge_reversed_cents": 0,
            "rider_ability_at_booking": rider_rank,
            "mount_release_count": 0,
            "checked_in_at": None,
            "completed_at": None,
            "cancelled_at": None,
        },
    )
    booking["activity_surcharge_total_cents"] = (
        int(booking["activity_surcharge_total_cents"]) + surcharge
    )
    touch = Touch()
    touch.add(booking)
    touch.slot(slot)
    touch.finalize()
    return created(reservation_json(row))


@bp.get("/activity-reservations/<reservation_id>")
def read_reservation(reservation_id):
    user_id, role = auth(*EVERYONE)
    seat = find("activity_reservations", reservation_id)
    if role == "Guest" and seat["guest_id"] != user_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "A guest may read only their own seats.")
    return ok(reservation_json(seat))


@bp.get("/activity-reservations")
def list_reservations():
    auth(*ALL_OPERATIONAL)
    rows = derive.rows_of(
        "activity_reservations",
        slot_id=fields.query_filter("slot_id"),
        booking_id=fields.query_filter("booking_id"),
        guest_id=fields.query_filter("guest_id"),
        assigned_horse_id=fields.query_filter("assigned_horse_id"),
        reservation_status=fields.query_enum("reservation_status", RESERVATION_STATUSES),
        mount_status=fields.query_enum("mount_status", MOUNT_STATUSES),
    )
    return listing(rows, reservation_json)


# --------------------------------------------------------------------- mounts
def _mountable_or_409(seat):
    """Precedence rule 20 for a mount write: the seat must be able to hold a horse."""
    if seat["reservation_status"] not in derive.LIVE_SEAT_STATUSES:
        raise ApiError(
            "ERR_RESERVATION_STATE_INVALID",
            "A %s seat cannot hold a mount." % seat["reservation_status"],
        )
    if seat["mount_status"] not in ("PENDING", "RELEASED"):
        raise ApiError(
            "ERR_RESERVATION_STATE_INVALID",
            "The seat's mount_status is %s." % seat["mount_status"],
        )


@bp.post("/activity-reservations/<reservation_id>/mount-assignments")
def assign_mount(reservation_id):
    auth("HorseProgramDirector")
    seat = find("activity_reservations", reservation_id)
    data = body()
    horse = find_body_ref("horses", data, "horse_id")
    require(data, "horse_id", "expected_horse_version")
    fields.as_str(data, "horse_id")
    pin = fields.as_int(data, "expected_horse_version")
    if horse is None:
        horse = find("horses", data["horse_id"])

    if pin != int(horse["version"]):
        raise ApiError(
            "ERR_STALE_HORSE_VERSION",
            "The supplied expected_horse_version is out of date.",
        )
    _mountable_or_409(seat)

    slot = _slot_of(seat)
    guest = db.guests.get(seat["guest_id"])
    if horse["horse_status"] != "IN_SERVICE":
        raise ApiError(
            "ERR_HORSE_NOT_IN_SERVICE",
            "The horse is %s and not available." % horse["horse_status"],
        )
    if calc.dec(guest["weight_lb"]) > calc.dec(horse["weight_limit_lb"]):
        raise ApiError(
            "ERR_RIDER_WEIGHT_EXCEEDS_MOUNT",
            "The rider exceeds the horse's weight limit.",
        )
    rider_rank = derive.effective_rank(guest)
    if (
        calc.RANKS[rider_rank] < calc.RANKS[horse["min_rider_ability"]]
        or calc.RANKS[rider_rank] > calc.RANKS[horse["max_rider_ability"]]
    ):
        raise ApiError(
            "ERR_MOUNT_ABILITY_MISMATCH",
            "The rider's rank falls outside the horse's ability band.",
        )
    if int(horse["consecutive_duty_days"]) >= calc.MAX_CONSECUTIVE_DUTY_DAYS:
        raise ApiError(
            "ERR_MOUNT_DUTY_LIMIT",
            "The horse has worked %d consecutive days." % int(horse["consecutive_duty_days"]),
        )
    daily = derive.daily_scheduled_hours(
        horse["id"], slot["starts_at"].date(), skip_seat_id=seat["id"]
    )
    if daily + calc.dec(slot["duration_hours"]) > calc.MAX_DAILY_MOUNT_HOURS:
        raise ApiError(
            "ERR_MOUNT_DAILY_HOURS_EXCEEDED",
            "The horse would exceed 4.0 scheduled hours on that date.",
        )
    if derive.mount_interval_conflict(horse["id"], slot, skip_seat_id=seat["id"]):
        raise ApiError(
            "ERR_MOUNT_INTERVAL_CONFLICT",
            "The horse needs a 60 minute recovery buffer between rides.",
        )

    touch = Touch()
    derive.attach_mount(seat, slot, horse, touch)
    touch.finalize()
    return ok(reservation_json(seat))


@bp.post("/activity-reservations/<reservation_id>/mount-auto-assign")
def auto_assign_mount(reservation_id):
    auth("HorseProgramDirector")
    seat = find("activity_reservations", reservation_id)
    _mountable_or_409(seat)
    slot = _slot_of(seat)
    guest = db.guests.get(seat["guest_id"])
    rider_rank = derive.effective_rank(guest)
    horse = derive.select_mount(seat, slot, guest, rider_rank)

    touch = Touch()
    derive.attach_mount(seat, slot, horse, touch)
    touch.finalize()
    return ok(reservation_json(seat))


@bp.post("/activity-reservations/<reservation_id>/mount-release")
def release_mount(reservation_id):
    auth("HorseProgramDirector")
    seat = find("activity_reservations", reservation_id)
    data = body()
    require(data, "reason")
    fields.as_str(data, "reason")

    slot = _slot_of(seat)
    if seat["mount_status"] != "ASSIGNED" or (
        slot is not None and slot["slot_status"] == "COMPLETED"
    ):
        raise ApiError(
            "ERR_RESERVATION_STATE_INVALID",
            "Only an ASSIGNED mount on an unfinished slot may be released.",
        )

    touch = Touch()
    derive.release_mount(seat, touch)
    touch.add(seat)
    touch.slot(slot)
    touch.finalize()
    return ok(reservation_json(seat))


# ---------------------------------------------------------- riding and reversal
@bp.post("/activity-reservations/<reservation_id>/check-in")
def check_in_rider(reservation_id):
    from routes_slots import assigned_guide_or_403

    user_id, role = auth("ActivityGuide")
    seat = find("activity_reservations", reservation_id)
    slot = _slot_of(seat)
    assigned_guide_or_403(slot, user_id)

    season = db.seasons.get(slot["season_id"]) if slot is not None else None
    if season is None or season["season_status"] != "IN_SEASON":
        raise ApiError(
            "ERR_SEASON_NOT_OPEN", "Checking a rider in requires an IN_SEASON season."
        )
    if seat["reservation_status"] != "CONFIRMED":
        raise ApiError(
            "ERR_RESERVATION_STATE_INVALID",
            "A %s seat cannot be checked in." % seat["reservation_status"],
        )
    if slot["slot_status"] != "RUNNING":
        raise ApiError(
            "ERR_RESERVATION_STATE_INVALID",
            "The slot is %s and not RUNNING." % slot["slot_status"],
        )

    guest = db.guests.get(seat["guest_id"])
    if guest["guest_standing"] == "SUSPENDED":
        raise ApiError("ERR_GUEST_SUSPENDED", "The guest is suspended.")
    if derive.waiver_status(guest) != "SIGNED":
        raise ApiError(
            "ERR_WAIVER_NOT_SIGNED", "The guest's waiver no longer resolves to SIGNED."
        )
    if slot["mount_required"] and guest.get("equine_statute_ack") is not True:
        raise ApiError(
            "ERR_EQUINE_STATUTE_ACK_REQUIRED",
            "A mounted ride requires the equine-activity acknowledgement.",
        )
    if seat["mount_status"] not in ("NOT_REQUIRED", "ASSIGNED"):
        raise ApiError(
            "ERR_RESERVATION_STATE_INVALID",
            "The rider has no mount in hand (mount_status %s)." % seat["mount_status"],
        )

    seat["reservation_status"] = "CHECKED_IN"
    seat["checked_in_at"] = db.clock_iso()
    db.touch(seat)
    return ok(reservation_json(seat))


@bp.post("/activity-reservations/<reservation_id>/cancel")
def cancel_reservation(reservation_id):
    auth("ReservationsAgent", "RanchManager")
    seat = find("activity_reservations", reservation_id)
    data = body()
    require(data, "reason")
    fields.as_str(data, "reason")

    slot = _slot_of(seat)
    slot_status = slot["slot_status"] if slot is not None else None
    legal = (
        seat["reservation_status"] == "CONFIRMED" and slot_status != "RUNNING"
    ) or (seat["reservation_status"] == "CHECKED_IN" and slot_status == "RUNNING")
    if not legal:
        raise ApiError(
            "ERR_RESERVATION_STATE_INVALID",
            "A %s seat on a %s slot cannot be cancelled."
            % (seat["reservation_status"], slot_status),
        )

    touch = Touch()
    derive.cancel_seat(seat, touch)
    touch.finalize()
    return ok(reservation_json(seat))
