"""Attraction sessions, tickets, dynamic pricing, and the waitlist (PRD 3.7)."""
from flask import request

from calculations import session_bounds, ticket_price_cents
from constants import (
    DURATION_MIN_MINUTES, GROUP_SIZE_MAX, GROUP_SIZE_MIN, OPS_ROLES,
    ROLE_BOX_OFFICE, ROLE_PLATFORM_ADMIN, SESSION_BUFFER_MINUTES,
    START_MINUTE_MAX,
)
from envelope import ok, paginate
from errors import ApiError
from store import STORE, parse_dt
from validation import (
    apply_filters, auth, body, get_or_404, new_entity, opt_bool,
    pagination_params, req_dt, req_enum, req_int, req_str, require_role, touch,
)


def serialize_session(s):
    return {
        "id": s["id"],
        "venue_name": s["venue_name"],
        "session_date": s["session_date"],
        "start_minute": s["start_minute"],
        "duration_minutes": s["duration_minutes"],
        "capacity_units": s["capacity_units"],
        "is_charter": s["is_charter"],
        "base_price_cents": s["base_price_cents"],
        "booked_units": s["booked_units"],
        "status": s["status"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def serialize_ticket(t):
    return {
        "id": t["id"],
        "session_id": t["session_id"],
        "kind": t["kind"],
        "group_size": t["group_size"],
        "school_name": t["school_name"],
        "units": t["units"],
        "price_cents": t["price_cents"],
        "status": t["status"],
        "checked_in_at": t["checked_in_at"],
        "waitlist_seq": t["waitlist_seq"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def create_session():
    _, role = auth()
    require_role(role, {ROLE_PLATFORM_ADMIN})
    data = body()
    venue_name = req_str(data, "venue_name")
    date_raw, session_date = req_dt(data, "session_date")
    start_minute = req_int(data, "start_minute")
    duration_minutes = req_int(data, "duration_minutes")
    capacity_units = req_int(data, "capacity_units")
    base_price_cents = req_int(data, "base_price_cents")
    is_charter = opt_bool(data, "is_charter", False)
    if start_minute < 0 or start_minute > START_MINUTE_MAX:
        raise ApiError("ERR_INVALID_REQUEST", "start_minute must be in 0..1339")
    if duration_minutes < DURATION_MIN_MINUTES:
        raise ApiError("ERR_INVALID_REQUEST", "duration_minutes must be >= 30")
    if capacity_units < 1:
        raise ApiError("ERR_INVALID_REQUEST", "capacity_units must be >= 1")
    if base_price_cents < 0:
        raise ApiError("ERR_INVALID_REQUEST", "base_price_cents must be >= 0")
    # Temporal (stage 8): session_date must not be before the current date.
    if session_date.date() < STORE.clock_dt.date():
        raise ApiError("ERR_DATE_ORDER")
    # Structural (stage 9): half-open buffered interval per venue+date.
    new_start = start_minute
    new_end = start_minute + duration_minutes + SESSION_BUFFER_MINUTES
    for other in STORE.sessions.values():
        if other["venue_name"] != venue_name or other["status"] != "SCHEDULED":
            continue
        if parse_dt(other["session_date"]).date() != session_date.date():
            continue
        other_start = other["start_minute"]
        other_end = other_start + other["duration_minutes"] + SESSION_BUFFER_MINUTES
        if new_start < other_end and other_start < new_end:
            raise ApiError("ERR_SESSION_WINDOW_CONFLICT")
    session = new_entity({
        "venue_name": venue_name,
        "session_date": date_raw,
        "start_minute": start_minute,
        "duration_minutes": duration_minutes,
        "capacity_units": capacity_units,
        "is_charter": is_charter,
        "base_price_cents": base_price_cents,
        "booked_units": 0,
        "status": "SCHEDULED",
    })
    STORE.sessions[session["id"]] = session
    return ok(serialize_session(session), status=201)


def get_session(session_id):
    _, role = auth()
    require_role(role, OPS_ROLES)
    session = get_or_404(STORE.sessions, session_id)
    return ok(serialize_session(session))


def list_session_tickets(session_id):
    _, role = auth()
    require_role(role, {ROLE_PLATFORM_ADMIN, ROLE_BOX_OFFICE})
    get_or_404(STORE.sessions, session_id)
    limit, offset = pagination_params()
    items = [t for t in STORE.tickets.values() if t["session_id"] == session_id]
    items = apply_filters(items, [
        ("status", request.args.get("status")),
        ("kind", request.args.get("kind")),
    ])
    items.sort(key=lambda t: (t["created_at"], t["waitlist_seq"]))
    page, meta = paginate(items, limit, offset)
    return ok([serialize_ticket(t) for t in page], response_type="array", pagination=meta)


def create_ticket():
    _, role = auth()
    require_role(role, {ROLE_BOX_OFFICE})
    data = body()
    session_id = req_str(data, "session_id")
    kind = req_enum(data, "kind", ("INDIVIDUAL", "GROUP"))
    group_size = None
    school_name = None
    if kind == "GROUP":
        group_size = req_int(data, "group_size")
        school_name = req_str(data, "school_name")
        if group_size < GROUP_SIZE_MIN:
            raise ApiError("ERR_INVALID_REQUEST", "group_size must be >= 10 for GROUP")
    else:
        if "group_size" in data or "school_name" in data:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "group_size and school_name must be omitted for INDIVIDUAL")
    session = get_or_404(STORE.sessions, session_id)
    # Group size upper bound (stage 9).
    if kind == "GROUP" and group_size > GROUP_SIZE_MAX:
        raise ApiError("ERR_GROUP_TOO_LARGE")
    units = group_size if kind == "GROUP" else 1
    # Capacity (stage 9): INDIVIDUALs never waitlist; equality still fits.
    fits = session["booked_units"] + units <= session["capacity_units"]
    if kind == "INDIVIDUAL" and not fits:
        raise ApiError("ERR_SESSION_FULL")
    # Linked state (stage 10): the session must still be SCHEDULED.
    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_CLOSED")
    ticket = new_entity({
        "session_id": session_id,
        "kind": kind,
        "group_size": group_size,
        "school_name": school_name,
        "units": units,
        "price_cents": None,
        "status": "CONFIRMED" if fits else "WAITLISTED",
        "checked_in_at": None,
        "waitlist_seq": STORE.next_scoped(STORE.waitlist_seq, session_id),
    })
    STORE.tickets[ticket["id"]] = ticket
    if fits:
        # Price fixed at confirmation, ratio measured before this booking.
        ticket["price_cents"] = ticket_price_cents(
            session, kind, units, session["booked_units"])
        session["booked_units"] += units
        touch(session)
    return ok(serialize_ticket(ticket), status=201)


def _promote_waitlist(session):
    """Strict head-of-line blocking promotion cascade after capacity frees."""
    while True:
        waiting = [t for t in STORE.tickets.values()
                   if t["session_id"] == session["id"] and t["status"] == "WAITLISTED"]
        if not waiting:
            return
        waiting.sort(key=lambda t: (t["created_at"], t["waitlist_seq"]))
        head = waiting[0]
        if session["booked_units"] + head["units"] > session["capacity_units"]:
            return  # head does not fit: stop the walk, no skipping
        head["price_cents"] = ticket_price_cents(
            session, head["kind"], head["units"], session["booked_units"])
        head["status"] = "CONFIRMED"
        touch(head)
        session["booked_units"] += head["units"]
        touch(session)


def ticket_decision(ticket_id):
    _, role = auth()
    require_role(role, {ROLE_BOX_OFFICE})
    data = body()
    action = req_enum(data, "action", ("CHECK_IN", "REFUND", "CANCEL"))
    ticket = get_or_404(STORE.tickets, ticket_id)
    session = STORE.sessions[ticket["session_id"]]
    # State gate (stage 6): the ticket state must permit the action.
    allowed = {"CHECK_IN": ("CONFIRMED",), "REFUND": ("CONFIRMED",), "CANCEL": ("WAITLISTED",)}
    if ticket["status"] not in allowed[action]:
        raise ApiError("ERR_TICKET_STATE")
    # Linked state (stage 10): the session must still be SCHEDULED.
    if session["status"] != "SCHEDULED":
        raise ApiError("ERR_SESSION_CLOSED")
    start, end = session_bounds(session)
    clock = STORE.clock_dt
    if action == "CHECK_IN":
        # Live window: from the session start through its end, inclusive.
        if not (start <= clock <= end):
            raise ApiError("ERR_TICKET_STATE")
        ticket["status"] = "CHECKED_IN"
        ticket["checked_in_at"] = STORE.clock_raw
        touch(ticket)
    elif action == "REFUND":
        # Refund window closes when the session begins.
        if not (clock < start):
            raise ApiError("ERR_TICKET_STATE")
        ticket["status"] = "REFUNDED"
        touch(ticket)
        session["booked_units"] -= ticket["units"]
        touch(session)
        _promote_waitlist(session)
    else:  # CANCEL
        ticket["status"] = "CANCELLED"
        touch(ticket)
    return ok(serialize_ticket(ticket))


def register(app):
    app.add_url_rule("/crayon-works/attraction-sessions",
                     view_func=create_session, methods=["POST"])
    app.add_url_rule("/crayon-works/attraction-sessions/<session_id>",
                     view_func=get_session, methods=["GET"])
    app.add_url_rule("/crayon-works/attraction-sessions/<session_id>/tickets",
                     view_func=list_session_tickets, methods=["GET"])
    app.add_url_rule("/crayon-works/tickets", view_func=create_ticket, methods=["POST"])
    app.add_url_rule("/crayon-works/tickets/<ticket_id>/decision",
                     view_func=ticket_decision, methods=["POST"])
