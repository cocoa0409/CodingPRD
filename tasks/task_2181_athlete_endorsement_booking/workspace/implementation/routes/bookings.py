"""Appearance logistics, travel accrual and production slots."""

from decimal import Decimal

from flask import Blueprint, request

import calc
import domain
import validation as V
from auth import ALL_ROLES, require
from envelope import created, ok, paginated, read_pagination
from errors import ApiError
from store import db, new_record, touch
from validation import parse_date, parse_datetime

bp = Blueprint("bookings", __name__)


@bp.post("/appearance-bookings")
def create_booking():
    require("TalentAgent")
    payload = V.body()
    engagement_id = V.id_field(payload, "engagement_id")
    city = V.str_field(payload, "city")
    start_raw, start_at = V.datetime_field(payload, "start_at")
    end_raw, end_at = V.datetime_field(payload, "end_at")
    if end_at <= start_at:
        V.bad("end_at must be strictly after start_at")
    travel_buffer_hours = V.int_field(payload, "travel_buffer_hours", minimum=0, maximum=72)
    expected_version = V.int_field(payload, "expected_engagement_version", minimum=0)

    engagement = domain.must_get("engagements", engagement_id)

    if expected_version != engagement["version"]:
        raise ApiError("ERR_STALE_ENGAGEMENT_VERSION",
                       "expected_engagement_version does not match the engagement")

    athlete = db.athletes[engagement["athlete_id"]]
    if athlete["status"] != "ACTIVE":
        raise ApiError("ERR_ATHLETE_NOT_BOOKABLE", "athlete is not ACTIVE on the roster")

    if engagement["contract_status"] not in ("PENDING_COUNTERSIGN", "ACTIVE"):
        raise ApiError("ERR_ENGAGEMENT_NOT_ACTIVE", "engagement is not open for bookings")

    if domain.calendar_conflict(athlete["id"], start_at, end_at, travel_buffer_hours):
        raise ApiError("ERR_BOOKING_OVERLAP", "the athlete's calendar is already occupied")

    term_start = parse_date(engagement["term_start_date"], "term_start_date")
    term_end = parse_date(engagement["term_end_date"], "term_end_date")
    if start_at.date() < term_start or end_at.date() > term_end:
        raise ApiError("ERR_BOOKING_WINDOW_OUTSIDE_TERM",
                       "the booking falls outside the engagement term")

    booking = new_record({
        "engagement_id": engagement_id,
        "city": city,
        "start_at": start_raw,
        "end_at": end_raw,
        "travel_buffer_hours": travel_buffer_hours,
        "travel_cost_cents": 0,
        "travel_days": 0,
        "status": "HOLD",
        "outcome": None,
        "cancel_reason_code": None,
    })
    db.appearance_bookings[booking["id"]] = booking
    touch(engagement)
    return created(booking)


@bp.get("/appearance-bookings/<booking_id>")
def get_booking(booking_id):
    require(ALL_ROLES)
    return ok(domain.must_get("appearance_bookings", booking_id))


@bp.get("/appearance-bookings")
def list_bookings():
    require(ALL_ROLES)
    limit, offset = read_pagination()
    rows = list(db.appearance_bookings.values())
    for field in ("engagement_id", "status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return paginated(rows, limit, offset)


@bp.post("/appearance-bookings/<booking_id>/confirm")
def confirm_booking(booking_id):
    require("TalentAgent")
    booking = domain.must_get("appearance_bookings", booking_id)
    payload = V.body()
    travel_cost_cents = V.int_field(payload, "travel_cost_cents", minimum=0)

    engagement = db.engagements[booking["engagement_id"]]
    if engagement["contract_status"] not in ("PENDING_COUNTERSIGN", "ACTIVE"):
        raise ApiError("ERR_ENGAGEMENT_NOT_ACTIVE", "engagement is not open for bookings")
    if booking["status"] != "HOLD":
        raise ApiError("ERR_BOOKING_INVALID_STATE", "booking is not on HOLD")

    booking["travel_cost_cents"] = travel_cost_cents
    booking["travel_days"] = calc.travel_days_for(
        parse_datetime(booking["start_at"], "start_at"),
        parse_datetime(booking["end_at"], "end_at"),
        booking["travel_buffer_hours"],
    )
    booking["status"] = "CONFIRMED"
    touch(booking)

    domain.append_ledger(engagement, "TRAVEL_ACCRUAL", travel_cost_cents,
                         "Travel accrual for confirmed appearance booking",
                         "AppearanceBooking", booking["id"])
    touch(engagement)
    return ok(booking)


@bp.post("/appearance-bookings/<booking_id>/close")
def close_booking(booking_id):
    require("TalentAgent")
    booking = domain.must_get("appearance_bookings", booking_id)
    payload = V.body()
    outcome = V.enum_field(payload, "outcome", calc.BOOKING_OUTCOMES)

    if booking["status"] != "CONFIRMED":
        raise ApiError("ERR_BOOKING_INVALID_STATE", "booking is not CONFIRMED")

    engagement = db.engagements[booking["engagement_id"]]
    booking["outcome"] = outcome
    booking["status"] = outcome
    touch(booking)

    if outcome == "NO_SHOW":
        athlete = db.athletes[engagement["athlete_id"]]
        domain.refresh_no_show_count(athlete)
        touch(athlete)
        penalty = calc.rhu_int(
            Decimal(engagement.get("binding_fee_cents") or 0) * calc.NO_SHOW_PENALTY_PCT)
        domain.append_ledger(engagement, "PENALTY", -penalty,
                             "No-show penalty on appearance booking",
                             "AppearanceBooking", booking["id"])
        touch(engagement)
    return ok(booking)


@bp.post("/appearance-bookings/<booking_id>/cancel")
def cancel_booking(booking_id):
    require("TalentAgent", "BrandRep")
    booking = domain.must_get("appearance_bookings", booking_id)
    payload = V.body()
    reason_code = V.str_field(payload, "reason_code")

    if booking["status"] not in ("HOLD", "CONFIRMED"):
        raise ApiError("ERR_BOOKING_INVALID_STATE", "booking is already terminal")

    engagement = db.engagements[booking["engagement_id"]]
    was_confirmed = booking["status"] == "CONFIRMED"
    booking["status"] = "CANCELLED"
    booking["cancel_reason_code"] = reason_code
    touch(booking)

    if was_confirmed:
        domain.append_ledger(engagement, "REVERSAL", -booking["travel_cost_cents"],
                             "Travel accrual reversed by booking cancellation",
                             "AppearanceBooking", booking["id"])
        touch(engagement)

    domain.void_booking_deliverables(booking)
    return ok(booking)


# ------------------------------------------------------------ production slots
@bp.post("/production-slots")
def create_slot():
    require("TalentAgent")
    payload = V.body()
    name = V.str_field(payload, "name")
    capacity = V.int_field(payload, "capacity", minimum=1)
    start_raw, window_start = V.datetime_field(payload, "window_start_at")
    end_raw, window_end = V.datetime_field(payload, "window_end_at")
    if window_end <= window_start:
        V.bad("window_end_at must be strictly after window_start_at")

    slot = new_record({
        "name": name,
        "capacity": capacity,
        "window_start_at": start_raw,
        "window_end_at": end_raw,
        "reserved_count": 0,
    })
    db.production_slots[slot["id"]] = slot
    return created(slot)


@bp.get("/production-slots/<slot_id>")
def get_slot(slot_id):
    require(ALL_ROLES)
    return ok(domain.must_get("production_slots", slot_id))
