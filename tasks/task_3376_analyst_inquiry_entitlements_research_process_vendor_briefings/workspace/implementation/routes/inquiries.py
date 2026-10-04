"""InquiryRequest endpoints (PRD 3.2, 3.3)."""

from datetime import timedelta

from flask import Blueprint, request

from db import db, serialize
from errors import ApiError, bad_request, invalid_state, unauthorized
from middleware import (
    authenticate,
    body,
    enum,
    optional_bool,
    optional_str,
    require_str,
)
from response import ok, ok_list
from services import routing, scoring, state
from timeutil import parse_dt, utc_date
from routes._common import page_of, require_inquiry, require_seat

bp = Blueprint("inquiries", __name__)

DURATIONS = (30, 45, 60)
OUTCOMES = ("COMPLETED", "NO_SHOW")
OPEN_STATUSES = ("SCHEDULED", "IN_PREP")


def _instant(data, field):
    value = require_str(data, field)
    parsed = parse_dt(value)
    if parsed is None:
        raise bad_request("Field %s must be an ISO 8601 instant." % field)
    return parsed


def _account_ledger(account):
    consumed, reserved = scoring.ledger_units(account["id"])
    allowance = account.get("inquiry_allowance_total", 0)
    return consumed, reserved, allowance - consumed - reserved


@bp.post("/research/inquiry-requests")
def create_inquiry():
    role, user_id = authenticate(["SeatHolder"])
    data = body()
    seat_id = require_str(data, "seat_id")
    topic_route = require_str(data, "topic_route")
    question_summary = require_str(data, "question_summary")
    requested_start = _instant(data, "requested_start_utc")
    duration = data.get("duration_minutes")
    if isinstance(duration, bool) or not isinstance(duration, int):
        raise bad_request("duration_minutes must be an integer.")
    enum(duration, DURATIONS, "duration_minutes")
    preparation_notes = optional_str(data, "preparation_notes", "")

    seat_obj = require_seat(seat_id)
    if role == "SeatHolder" and user_id != seat_obj["id"]:
        raise unauthorized("A SeatHolder may only submit inquiries from its own seat.")

    if requested_start < db.now():
        raise ApiError(
            "ERR_INQUIRY_START_IN_PAST",
            "The requested start instant is strictly before the logical clock.",
            400,
        )

    account = state.account_of_seat(seat_obj)
    if seat_obj.get("status") != "ACTIVE" or account is None or account.get("contract_status") != "ACTIVE":
        raise ApiError(
            "ERR_SEAT_NOT_ACTIVE",
            "The seat and its account must both be ACTIVE to submit an inquiry.",
            409,
        )

    winner = routing.topic_route_winner(topic_route, [])
    if winner is None:
        raise ApiError(
            "ERR_ANALYST_NOT_ELIGIBLE",
            "Topic routing found no eligible analyst for this topic route.",
            409,
        )

    inquiry_obj = db.create(
        seat_id=seat_obj["id"],
        analyst_id=winner["id"],
        topic_route=topic_route,
        question_summary=question_summary,
        preparation_notes=preparation_notes,
        requested_start_utc=requested_start,
        duration_minutes=duration,
        scheduled_start_utc=None,
        status="ROUTED",
        units_consumed=0,
        note_delivered=False,
        note_reference="",
        routing_attempt_count=1,
        declined_analyst_ids=[],
        settled_at=None,
    )
    db.inquiries[inquiry_obj["id"]] = inquiry_obj

    seat_obj["last_inquiry_at"] = db.now()
    db.touch(seat_obj)
    state.refresh_analyst(winner)
    scoring.refresh_account(account)
    return ok(serialize(inquiry_obj), 201)


@bp.get("/research/inquiry-requests/<inquiry_id>")
def read_inquiry(inquiry_id):
    authenticate(["SeatHolder", "Analyst", "PlatformAdmin", "ResearchDirector", "ClientAdmin"])
    inquiry_obj = require_inquiry(inquiry_id)
    state.evaluate_inquiry(inquiry_obj)
    return ok(serialize(inquiry_obj), 200)


@bp.get("/research/inquiry-requests")
def list_inquiries():
    authenticate(["SeatHolder", "Analyst", "PlatformAdmin", "ResearchDirector", "ClientAdmin"])
    items = list(db.inquiries.values())
    seat_id = request.args.get("seat_id")
    analyst_id = request.args.get("analyst_id")
    status = request.args.get("status")
    if seat_id:
        items = [q for q in items if q.get("seat_id") == seat_id]
    if analyst_id:
        items = [q for q in items if q.get("analyst_id") == analyst_id]
    if status:
        items = [q for q in items if q.get("status") == status]
    page, limit, offset, total = page_of(items)
    return ok_list(page, limit, offset, total)


def _own_inquiry(role, user_id, inquiry_obj):
    if role == "Analyst" and user_id != inquiry_obj.get("analyst_id"):
        raise unauthorized("Only the assigned analyst may act on this inquiry.")


def _other_open_windows(analyst_id, exclude_id):
    windows = []
    for other in db.inquiries.values():
        if other["id"] == exclude_id:
            continue
        if other.get("analyst_id") != analyst_id:
            continue
        if other.get("status") not in OPEN_STATUSES:
            continue
        start = parse_dt(other.get("scheduled_start_utc"))
        if start is None:
            continue
        windows.append((start, start + timedelta(minutes=other.get("duration_minutes", 0))))
    return windows


@bp.post("/research/inquiry-requests/<inquiry_id>/schedule")
def schedule_inquiry(inquiry_id):
    role, user_id = authenticate(["Analyst"])
    data = body()
    start = _instant(data, "scheduled_start_utc")
    inquiry_obj = require_inquiry(inquiry_id)
    _own_inquiry(role, user_id, inquiry_obj)
    state.evaluate_inquiry(inquiry_obj)

    if inquiry_obj.get("status") != "ROUTED":
        raise invalid_state("Only a ROUTED inquiry can be scheduled.")

    if start < db.now():
        raise ApiError(
            "ERR_INQUIRY_START_IN_PAST",
            "The confirmed start instant is strictly before the logical clock.",
            400,
        )

    end = start + timedelta(minutes=inquiry_obj.get("duration_minutes", 0))
    for window_start, window_end in _other_open_windows(inquiry_obj.get("analyst_id"), inquiry_obj["id"]):
        if start < window_end and window_start < end:
            raise ApiError(
                "ERR_INQUIRY_SLOT_OVERLAP",
                "The requested window overlaps another open inquiry of this analyst.",
                409,
            )

    same_day = 0
    for other in db.inquiries.values():
        if other["id"] == inquiry_obj["id"]:
            continue
        if other.get("analyst_id") != inquiry_obj.get("analyst_id"):
            continue
        if other.get("status") not in OPEN_STATUSES:
            continue
        other_start = parse_dt(other.get("scheduled_start_utc"))
        if other_start is not None and utc_date(other_start) == utc_date(start):
            same_day += 1
    if same_day >= 3:
        raise ApiError(
            "ERR_ANALYST_DAILY_INQUIRY_CAP",
            "The analyst already holds 3 inquiries on that UTC calendar day.",
            409,
        )

    account = state.account_of_inquiry(inquiry_obj)
    _, _, remaining_reserved = _account_ledger(account)
    if remaining_reserved < 1:
        raise ApiError(
            "ERR_INQUIRY_ALLOWANCE_EXHAUSTED",
            "The reservation ledger has no free unit for this account.",
            409,
        )

    inquiry_obj["status"] = "SCHEDULED"
    inquiry_obj["scheduled_start_utc"] = start
    db.touch(inquiry_obj)
    scoring.refresh_account(account)
    return ok(serialize(inquiry_obj), 200)


@bp.post("/research/inquiry-requests/<inquiry_id>/decline")
def decline_inquiry(inquiry_id):
    role, user_id = authenticate(["Analyst"])
    data = body()
    optional_str(data, "decline_reason", "")
    inquiry_obj = require_inquiry(inquiry_id)
    _own_inquiry(role, user_id, inquiry_obj)
    state.evaluate_inquiry(inquiry_obj)

    if inquiry_obj.get("status") != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED inquiry can be declined.")

    previous_id = inquiry_obj.get("analyst_id")
    declined = list(inquiry_obj.get("declined_analyst_ids") or [])
    declined.append(previous_id)
    winner = routing.topic_route_winner(inquiry_obj.get("topic_route"), declined)
    if winner is None:
        raise ApiError(
            "ERR_ANALYST_NOT_ELIGIBLE",
            "No eligible analyst remains to take this inquiry.",
            409,
        )

    inquiry_obj["declined_analyst_ids"] = declined
    inquiry_obj["analyst_id"] = winner["id"]
    inquiry_obj["routing_attempt_count"] = inquiry_obj.get("routing_attempt_count", 0) + 1
    inquiry_obj["status"] = "ROUTED"
    inquiry_obj["scheduled_start_utc"] = None
    db.touch(inquiry_obj)

    previous = db.analysts.get(previous_id)
    if previous is not None:
        state.refresh_analyst(previous)
    state.refresh_analyst(winner)
    account = state.account_of_inquiry(inquiry_obj)
    if account is not None:
        scoring.refresh_account(account)
    return ok(serialize(inquiry_obj), 200)


@bp.post("/research/inquiry-requests/<inquiry_id>/complete")
def complete_inquiry(inquiry_id):
    role, user_id = authenticate(["Analyst"])
    data = body()
    outcome = enum(require_str(data, "outcome"), OUTCOMES, "outcome")
    note_delivered = optional_bool(data, "note_delivered", False)
    note_reference = optional_str(data, "note_reference", "")
    inquiry_obj = require_inquiry(inquiry_id)
    _own_inquiry(role, user_id, inquiry_obj)
    state.evaluate_inquiry(inquiry_obj)

    if inquiry_obj.get("status") != "IN_PREP":
        raise invalid_state("Only an IN_PREP inquiry can be completed.")

    start = parse_dt(inquiry_obj.get("scheduled_start_utc"))
    if start is None or db.now() < start:
        raise invalid_state("The clock has not yet reached the scheduled start instant.")

    if outcome == "COMPLETED":
        if not note_delivered or not (inquiry_obj.get("preparation_notes") or "").strip():
            raise ApiError(
                "ERR_PREPARATION_NOTES_REQUIRED",
                "A COMPLETED inquiry requires preparation notes and a delivered note.",
                409,
            )

    inquiry_obj["status"] = outcome
    inquiry_obj["units_consumed"] = 1
    inquiry_obj["settled_at"] = db.now()
    if outcome == "COMPLETED":
        inquiry_obj["note_delivered"] = True
        inquiry_obj["note_reference"] = note_reference
    else:
        inquiry_obj["note_delivered"] = False
    db.touch(inquiry_obj)

    analyst_obj = db.analysts.get(inquiry_obj.get("analyst_id"))
    if analyst_obj is not None:
        if outcome == "COMPLETED":
            analyst_obj["inquiries_completed_total"] = (
                analyst_obj.get("inquiries_completed_total", 0) + 1
            )
            db.touch(analyst_obj)
        state.refresh_analyst(analyst_obj)

    account = state.account_of_inquiry(inquiry_obj)
    if account is not None:
        scoring.refresh_account(account)
    return ok(serialize(inquiry_obj), 200)


@bp.post("/research/inquiry-requests/<inquiry_id>/cancel")
def cancel_inquiry(inquiry_id):
    role, user_id = authenticate(["SeatHolder", "ClientAdmin"])
    data = body()
    optional_str(data, "cancel_reason", "")
    inquiry_obj = require_inquiry(inquiry_id)
    seat_obj = db.seats.get(inquiry_obj.get("seat_id"))

    if role == "SeatHolder":
        if user_id != inquiry_obj.get("seat_id"):
            raise unauthorized("A SeatHolder may only cancel its own inquiries.")
    else:
        if seat_obj is None or user_id != seat_obj.get("client_account_id"):
            raise unauthorized("A ClientAdmin may only cancel inquiries of its own account.")

    state.evaluate_inquiry(inquiry_obj)
    if inquiry_obj.get("status") not in ("ROUTED", "SCHEDULED", "IN_PREP"):
        raise invalid_state("A terminal inquiry cannot be cancelled.")

    # The charge is decided by the pinned 24-hour boundary, not by the status the
    # clock-driven evaluation just produced: PRD 2.4 pins cancellation as "free
    # while the clock reading is at or before scheduled_start_utc minus 24 hours,
    # and late once the clock reading is strictly after that instant", and 3.3
    # states the same rule for "a scheduled or in-preparation inquiry".  At the
    # exact boundary the inquiry has reached — not crossed — the boundary, so the
    # inclusive free branch applies even though it has just entered IN_PREP.
    status = inquiry_obj.get("status")
    start = parse_dt(inquiry_obj.get("scheduled_start_utc"))
    if status == "ROUTED" or start is None:
        inquiry_obj["units_consumed"] = 0
    else:
        free_until = start - timedelta(hours=24)
        inquiry_obj["units_consumed"] = 0 if db.now() <= free_until else 1

    inquiry_obj["status"] = "CANCELLED"
    inquiry_obj["settled_at"] = db.now()
    db.touch(inquiry_obj)

    analyst_obj = db.analysts.get(inquiry_obj.get("analyst_id"))
    if analyst_obj is not None:
        state.refresh_analyst(analyst_obj)
    account = state.account_of_inquiry(inquiry_obj)
    if account is not None:
        scoring.refresh_account(account)
    return ok(serialize(inquiry_obj), 200)
