"""Markets, screening slots and buyer meetings."""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, request

from calc import MEETING_MINUTES_CAP, TURNAROUND_MINUTES
from envelope import created, ok, ok_list
from errors import ApiError
from serializers import market_out, meeting_out, slot_out
from store import (
    base_row,
    by_creation,
    db,
    get_buyer,
    get_film,
    get_market,
    get_meeting,
    get_slot,
    meetings_of_market,
    slots_of_market,
    touch,
)
from util import whole_minutes_between
from validation import body, page, raw_id, require_roles

bp = Blueprint("markets", __name__)

MARKET_STATUSES = ("PLANNED", "OPEN", "CLOSED")
SLOT_STATUSES = ("HELD", "CONFIRMED", "CANCELLED")
SLOT_TYPES = ("BUYER_SCREENING", "PRESS", "MARKET_PREMIERE")
MEETING_STATUSES = ("SCHEDULED", "COMPLETED", "NO_SHOW", "CANCELLED")
MEETING_OUTCOMES = ("PASS", "INTERESTED", "OFFER_REQUESTED")

MARKET_ROLES = ("SalesAgent", "HeadOfSales", "DeliveryManager", "PlatformAdmin")
MEETING_READ_ROLES = (
    "SalesAgent",
    "HeadOfSales",
    "DeliveryManager",
    "PlatformAdmin",
    "Buyer",
)

FILM_MARKET_READY = ("PACKAGING", "IN_MARKET")
SLOT_LIVE = ("HELD", "CONFIRMED")
MEETING_LIVE = ("SCHEDULED", "COMPLETED", "NO_SHOW")


# -------------------------------------------------------------------- markets


@bp.post("/markets")
@require_roles("PlatformAdmin")
def create_market():
    payload = body()
    name = payload.req_string("name")
    city = payload.req_string("city")
    start_date = payload.req_instant("start_date")
    end_date = payload.req_instant("end_date")
    if end_date <= start_date:
        raise ApiError(
            "ERR_INVALID_REQUEST", "Field 'end_date' must be after 'start_date'."
        )
    row = base_row()
    row.update(
        {
            "name": name,
            "city": city,
            "start_date": start_date,
            "end_date": end_date,
            "screening_room_count": payload.req_int("screening_room_count", minimum=1),
            "meeting_table_count": payload.req_int("meeting_table_count", minimum=1),
            "status": "PLANNED",
        }
    )
    db.markets[row["id"]] = row
    return created(market_out(row))


@bp.get("/markets")
@require_roles(*MARKET_ROLES)
def list_markets():
    rows = list(db.markets.values())
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    rows.sort(key=lambda r: (r["start_date"], r["created_at"], r["_seq"]))
    items, meta = page(rows, market_out)
    return ok_list(items, meta)


@bp.get("/markets/<market_id>")
@require_roles(*MARKET_ROLES)
def read_market(market_id):
    return ok(market_out(get_market(market_id)))


@bp.post("/markets/<market_id>/state")
@require_roles("PlatformAdmin")
def market_state(market_id):
    market = get_market(market_id)
    payload = body()
    to_status = payload.req_enum("to_status", MARKET_STATUSES)
    current = market["status"]
    if to_status == current:
        raise ApiError("ERR_INVALID_STATE")
    if to_status == "OPEN":
        if current != "PLANNED":
            raise ApiError("ERR_INVALID_STATE")
        if market["end_date"] <= market["start_date"]:
            raise ApiError("ERR_INVALID_STATE")
        market["status"] = "OPEN"
        touch(market)
    elif to_status == "CLOSED":
        if current != "OPEN":
            raise ApiError("ERR_INVALID_STATE")
        market["status"] = "CLOSED"
        touch(market)
        for slot in slots_of_market(market["id"]):
            if slot["status"] == "HELD":
                slot["status"] = "CANCELLED"
                touch(slot)
        for meeting in meetings_of_market(market["id"]):
            if meeting["status"] == "SCHEDULED":
                meeting["status"] = "NO_SHOW"
                touch(meeting)
    else:
        raise ApiError("ERR_INVALID_STATE")
    return ok(market_out(market))


# ------------------------------------------------------------ screening slots


@bp.post("/screening-slots")
@require_roles("SalesAgent", "HeadOfSales")
def create_slot():
    film_ref = raw_id("film_id")
    film = get_film(film_ref) if film_ref is not None else None
    market_ref = raw_id("market_id")
    market = get_market(market_ref) if market_ref is not None else None
    payload = body()
    payload.req_id("market_id")
    payload.req_id("film_id")
    room_number = payload.req_int(
        "room_number", minimum=1, maximum=market["screening_room_count"]
    )
    start_at = payload.req_instant("start_at")
    end_at = payload.req_instant("end_at")
    if end_at <= start_at:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'end_at' must be after 'start_at'.")
    slot_type = payload.req_enum("slot_type", SLOT_TYPES)
    capacity = payload.req_int("capacity", minimum=1)

    if film["sales_status"] not in FILM_MARKET_READY:
        raise ApiError("ERR_FILM_NOT_IN_MARKET")
    if market["status"] != "OPEN":
        raise ApiError("ERR_MARKET_NOT_OPEN")

    buffer = timedelta(minutes=TURNAROUND_MINUTES)
    for existing in slots_of_market(market["id"]):
        if existing["status"] not in SLOT_LIVE:
            continue
        if existing["room_number"] != room_number:
            continue
        if start_at < existing["end_at"] + buffer and existing["start_at"] < end_at + buffer:
            raise ApiError("ERR_SCREENING_ROOM_CONFLICT")

    if start_at < market["start_date"] or end_at > market["end_date"]:
        raise ApiError("ERR_OUTSIDE_MARKET_WINDOW")

    row = base_row()
    row.update(
        {
            "market_id": market["id"],
            "film_id": film["id"],
            "room_number": room_number,
            "start_at": start_at,
            "end_at": end_at,
            "slot_type": slot_type,
            "capacity": capacity,
            "status": "HELD",
        }
    )
    db.slots[row["id"]] = row
    return created(slot_out(row))


@bp.get("/screening-slots")
@require_roles(*MARKET_ROLES)
def list_slots():
    rows = list(db.slots.values())
    for key in ("market_id", "film_id", "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    room_number = request.args.get("room_number")
    if room_number:
        rows = [r for r in rows if str(r["room_number"]) == str(room_number)]
    rows.sort(key=lambda r: (r["start_at"], r["created_at"], r["_seq"]))
    items, meta = page(rows, slot_out)
    return ok_list(items, meta)


@bp.get("/screening-slots/<slot_id>")
@require_roles(*MARKET_ROLES)
def read_slot(slot_id):
    return ok(slot_out(get_slot(slot_id)))


@bp.post("/screening-slots/<slot_id>/state")
@require_roles("SalesAgent", "HeadOfSales")
def slot_state(slot_id):
    slot = get_slot(slot_id)
    payload = body()
    to_status = payload.req_enum("to_status", SLOT_STATUSES)
    current = slot["status"]
    if to_status == current:
        raise ApiError("ERR_INVALID_STATE")
    if to_status == "CONFIRMED":
        if current != "HELD":
            raise ApiError("ERR_INVALID_STATE")
        market = db.markets.get(slot["market_id"])
        if market is None or market["status"] != "OPEN":
            raise ApiError("ERR_MARKET_NOT_OPEN")
        slot["status"] = "CONFIRMED"
        touch(slot)
    elif to_status == "CANCELLED":
        if current not in SLOT_LIVE:
            raise ApiError("ERR_INVALID_STATE")
        slot["status"] = "CANCELLED"
        touch(slot)
    else:
        raise ApiError("ERR_INVALID_STATE")
    return ok(slot_out(slot))


# -------------------------------------------------------------- buyer meetings


@bp.post("/buyer-meetings")
@require_roles("SalesAgent", "HeadOfSales")
def create_meeting():
    film_ref = raw_id("film_id")
    film = get_film(film_ref) if film_ref is not None else None
    market_ref = raw_id("market_id")
    market = get_market(market_ref) if market_ref is not None else None
    buyer_ref = raw_id("buyer_id")
    buyer = get_buyer(buyer_ref) if buyer_ref is not None else None
    payload = body()
    payload.req_id("market_id")
    payload.req_id("buyer_id")
    payload.req_id("film_id")
    table_number = payload.req_int(
        "table_number", minimum=1, maximum=market["meeting_table_count"]
    )
    start_at = payload.req_instant("start_at")
    end_at = payload.req_instant("end_at")
    if end_at <= start_at:
        raise ApiError("ERR_INVALID_REQUEST", "Field 'end_at' must be after 'start_at'.")

    if film["sales_status"] not in FILM_MARKET_READY:
        raise ApiError("ERR_FILM_NOT_IN_MARKET")
    if market["status"] != "OPEN":
        raise ApiError("ERR_MARKET_NOT_OPEN")
    if buyer["status"] == "BLOCKED":
        raise ApiError("ERR_BUYER_BLOCKED")

    live = [m for m in meetings_of_market(market["id"]) if m["status"] in MEETING_LIVE]
    for existing in live:
        same_resource = (
            existing["table_number"] == table_number
            or existing["buyer_id"] == buyer["id"]
        )
        if not same_resource:
            continue
        if start_at < existing["end_at"] and existing["start_at"] < end_at:
            raise ApiError("ERR_MEETING_SLOT_CONFLICT")

    if start_at < market["start_date"] or end_at > market["end_date"]:
        raise ApiError("ERR_OUTSIDE_MARKET_WINDOW")

    duration = whole_minutes_between(start_at, end_at)
    booked = sum(
        m["duration_minutes"] for m in live if m["buyer_id"] == buyer["id"]
    )
    if booked + duration > MEETING_MINUTES_CAP:
        raise ApiError("ERR_MEETING_MINUTES_CAP_EXCEEDED")

    row = base_row()
    row.update(
        {
            "market_id": market["id"],
            "buyer_id": buyer["id"],
            "film_id": film["id"],
            "table_number": table_number,
            "start_at": start_at,
            "end_at": end_at,
            "duration_minutes": duration,
            "status": "SCHEDULED",
            "outcome": None,
        }
    )
    db.meetings[row["id"]] = row
    return created(meeting_out(row))


@bp.get("/buyer-meetings")
@require_roles(*MEETING_READ_ROLES)
def list_meetings():
    rows = list(db.meetings.values())
    for key in ("market_id", "buyer_id", "film_id", "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    table_number = request.args.get("table_number")
    if table_number:
        rows = [r for r in rows if str(r["table_number"]) == str(table_number)]
    rows.sort(key=lambda r: (r["start_at"], r["created_at"], r["_seq"]))
    items, meta = page(rows, meeting_out)
    return ok_list(items, meta)


@bp.get("/buyer-meetings/<meeting_id>")
@require_roles(*MEETING_READ_ROLES)
def read_meeting(meeting_id):
    return ok(meeting_out(get_meeting(meeting_id)))


@bp.post("/buyer-meetings/<meeting_id>/state")
@require_roles("SalesAgent", "HeadOfSales")
def meeting_state(meeting_id):
    meeting = get_meeting(meeting_id)
    payload = body()
    to_status = payload.req_enum("to_status", MEETING_STATUSES)
    outcome = None
    if to_status == "COMPLETED":
        outcome = payload.req_enum("outcome", MEETING_OUTCOMES)
    current = meeting["status"]
    if to_status == current:
        raise ApiError("ERR_INVALID_STATE")
    if current != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE")
    if to_status not in ("COMPLETED", "NO_SHOW", "CANCELLED"):
        raise ApiError("ERR_INVALID_STATE")
    meeting["status"] = to_status
    if to_status == "COMPLETED":
        meeting["outcome"] = outcome
    touch(meeting)
    return ok(meeting_out(meeting))
