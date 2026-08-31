"""Remembrance events and family invitations (§3.7)."""

from flask import Blueprint, request

from core import calc
from core.auth import authenticate, own_participant_field
from core.envelope import created, listing, ok
from core.errors import ApiError
from core.shape import (RESPONSES, bad, body, iso_date, opt_int, parse_date, req_date,
                        req_enum, req_int, req_str)
from core.store import add_days, public, store
from services import cascade, occupation
from services.state import must_exist, require_participant_active, transition

bp = Blueprint("events", __name__)

READ_ROLES = ["ProgramDirector", "IntakeCoordinator"]
RSVP_LEAD_DAYS = 3


@bp.route("/bereavement/remembrance-events", methods=["POST"])
def create_event():
    authenticate(["ProgramDirector"])
    data = body()
    title = req_str(data, "title")
    space_id = req_str(data, "meeting_space_id")
    event_date = req_date(data, "event_date")
    start_minute = req_int(data, "start_minute_utc", 0, 1439)
    duration = req_int(data, "duration_minutes", 1)
    expected = req_int(data, "expected_attendance", 1)
    direct_cost = req_int(data, "direct_cost_cents", 0)
    if start_minute + duration > 1440:
        bad("start_minute_utc + duration_minutes must not exceed 1440.")

    space = must_exist("MeetingSpace", space_id)

    if event_date < store.today():
        raise ApiError("ERR_EVENT_DATE_IN_PAST", "event_date is earlier than the logical clock date.")
    occupation.check_event(space, event_date, start_minute, duration)

    if expected > space["capacity"]:
        raise ApiError("ERR_SPACE_CAPACITY_EXCEEDED", "expected_attendance exceeds the space capacity.")

    admin_fee, total = calc.program_cost(direct_cost)
    rec = store.create("RemembranceEvent", {
        "title": title,
        "meeting_space_id": space_id,
        "event_date": iso_date(event_date),
        "start_minute_utc": start_minute,
        "duration_minutes": duration,
        "expected_attendance": expected,
        "status": "PLANNED",
        "invitations_sent": 0,
        "invitations_accepted": 0,
        "confirmed_headcount": 0,
        "direct_cost_cents": direct_cost,
        "admin_fee_cents": admin_fee,
        "program_cost_total_cents": total,
    })
    return created(public(rec))


@bp.route("/bereavement/remembrance-events/<eid>", methods=["GET"])
def read_event(eid):
    authenticate(READ_ROLES)
    return ok(public(must_exist("RemembranceEvent", eid)))


@bp.route("/bereavement/remembrance-events", methods=["GET"])
def list_events():
    authenticate(READ_ROLES)
    rows = store.all("RemembranceEvent")
    for key in ("meeting_space_id", "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return listing(rows, public)


@bp.route("/bereavement/remembrance-events/<eid>/confirm", methods=["POST"])
def confirm_event(eid):
    authenticate(["ProgramDirector"])
    event = must_exist("RemembranceEvent", eid)
    body()
    transition(event, {"PLANNED"})
    space = store.get("MeetingSpace", event["meeting_space_id"])
    if space is None or space["status"] != "AVAILABLE":
        raise ApiError("ERR_INVALID_STATE", "The meeting space is not AVAILABLE.")
    event["status"] = "CONFIRMED"
    store.touch(event)
    return ok(public(event))


@bp.route("/bereavement/remembrance-events/<eid>/cancel", methods=["POST"])
def cancel_event(eid):
    authenticate(["ProgramDirector"])
    event = must_exist("RemembranceEvent", eid)
    body()
    transition(event, {"PLANNED", "CONFIRMED"})
    event["status"] = "CANCELLED"
    for inv in store.find("Invitation", event_id=eid):
        if inv["status"] in ("DRAFT", "SENT"):
            inv["status"] = "VOID"
            store.touch(inv)
    cascade.release_allocations_for_event(event)
    store.touch(event)
    return ok(public(event))


@bp.route("/bereavement/remembrance-events/<eid>/mark-held", methods=["POST"])
def mark_held(eid):
    authenticate(["ProgramDirector"])
    event = must_exist("RemembranceEvent", eid)
    body()
    transition(event, {"CONFIRMED"})
    if store.today() < parse_date(event["event_date"], "event_date"):
        raise ApiError("ERR_INVALID_STATE", "The event date has not been reached.")
    event["status"] = "HELD"
    for inv in store.find("Invitation", event_id=eid):
        if inv["status"] in ("DRAFT", "SENT"):
            inv["status"] = "EXPIRED"
            store.touch(inv)
    cascade.settle_allocations_for_event(event)
    store.touch(event)
    return ok(public(event))


# ------------------------------------------------------------- invitations
@bp.route("/bereavement/invitations", methods=["POST"])
def create_invitation():
    authenticate(["IntakeCoordinator"])
    data = body()
    event_id = req_str(data, "event_id")
    participant_id = req_str(data, "participant_id")
    guest_count = opt_int(data, "guest_count", 0, 0)

    event = must_exist("RemembranceEvent", event_id)
    participant = must_exist("Participant", participant_id)
    require_participant_active(participant)

    deadline = add_days(parse_date(event["event_date"], "event_date"), -RSVP_LEAD_DAYS)
    rec = store.create("Invitation", {
        "event_id": event_id,
        "participant_id": participant_id,
        "guest_count": guest_count,
        "status": "DRAFT",
        "rsvp_deadline": iso_date(deadline),
        "sent_at": None,
        "responded_at": None,
    })
    return created(public(rec))


@bp.route("/bereavement/invitations/<iid>", methods=["GET"])
def read_invitation(iid):
    ctx = authenticate(["IntakeCoordinator", "ProgramDirector", "Participant"])
    inv = must_exist("Invitation", iid)
    own_participant_field(ctx, inv)
    return ok(public(inv))


@bp.route("/bereavement/invitations", methods=["GET"])
def list_invitations():
    authenticate(["IntakeCoordinator", "ProgramDirector"])
    rows = store.all("Invitation")
    for key in ("event_id", "participant_id", "status"):
        value = request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return listing(rows, public)


@bp.route("/bereavement/invitations/<iid>/send", methods=["POST"])
def send_invitation(iid):
    authenticate(["IntakeCoordinator"])
    inv = must_exist("Invitation", iid)
    body()
    transition(inv, {"DRAFT"})
    event = store.get("RemembranceEvent", inv["event_id"])
    if event is None or event["status"] != "CONFIRMED":
        raise ApiError("ERR_EVENT_NOT_CONFIRMED", "The event is not CONFIRMED.")
    if store.today().isoformat() > inv["rsvp_deadline"]:
        raise ApiError("ERR_RSVP_WINDOW_CLOSED", "The RSVP window has closed.")
    inv["status"] = "SENT"
    inv["sent_at"] = store.now_iso()
    store.touch(inv)
    event["invitations_sent"] += 1
    store.touch(event)
    return ok(public(inv))


@bp.route("/bereavement/invitations/<iid>/respond", methods=["POST"])
def respond_invitation(iid):
    ctx = authenticate(["Participant", "IntakeCoordinator"])
    inv = must_exist("Invitation", iid)
    own_participant_field(ctx, inv)
    data = body()
    response = req_enum(data, "response", RESPONSES)
    transition(inv, {"SENT"})
    if store.today().isoformat() > inv["rsvp_deadline"]:
        raise ApiError("ERR_RSVP_WINDOW_CLOSED", "The RSVP window has closed.")
    inv["responded_at"] = store.now_iso()
    event = store.get("RemembranceEvent", inv["event_id"])
    if response == "ACCEPT":
        inv["status"] = "ACCEPTED"
        if event is not None:
            event["invitations_accepted"] += 1
            event["confirmed_headcount"] += 1 + inv["guest_count"]
            store.touch(event)
    else:
        inv["status"] = "DECLINED"
    store.touch(inv)
    return ok(public(inv))
