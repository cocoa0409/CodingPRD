"""Flight endpoints (PRD 3.2, 3.3, 3.5, 3.6, 3.7): compose, publish battery,
dawn operations, launch/land/close, cancel/reschedule, site selection."""
from datetime import timedelta

from flask import Blueprint, request

from db import db
from errors import (
    raise_error, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_STALE_VERSION, ERR_FLIGHT_NOT_ASSIGNED, ERR_SITE_PERMISSION_NOT_GRANTED,
    ERR_BALLOON_GROUNDED, ERR_PILOT_NOT_CURRENT, ERR_BALLOON_SCHEDULE_CONFLICT,
    ERR_PILOT_SCHEDULE_CONFLICT, ERR_DAWN_WINDOW_EXPIRED, ERR_CHASE_NOT_READY,
    ERR_PAYLOAD_EXCEEDED, ERR_WEATHER_LIMITS_EXCEEDED,
)
from middleware import (
    authorized, ALL_READ_ROLES, peek_event_type, check_event_slice,
)
from response import success_object, success_list
from services.cascades import cancel_flight_cascade
from services.calculations import site_candidates, select_site_or_raise, latest_recorded_briefing
from services.core import (
    new_record, touch, public_flight, compute_currency, flight_payload_used,
    sort_created, ACTIVE_FLIGHT_STATES,
)
from util import parse_date, parse_datetime, fmt_datetime, CLOCK
from validate import (
    get_body, req_str, req_date, req_datetime, req_int, opt_int, opt_number,
    req_enum, require_path_resource, get_pagination,
)

bp = Blueprint("flights", __name__, url_prefix="/v1")

OM_EVENTS = {"PUBLISH", "RESCHEDULE", "CANCEL", "CLOSE"}
PILOT_EVENTS = {"ENTER_WEATHER_REVIEW", "RECORD_GO", "RECORD_NO_GO", "LAUNCH", "LAND"}
ALL_EVENTS = OM_EVENTS | PILOT_EVENTS
EVENT_SLICES = {"OperationsManager": OM_EVENTS, "Pilot": PILOT_EVENTS}


def _validate_dawn_window(scheduled_date, start_str, end_str):
    """Priority 4: window is exactly 90 minutes and starts on scheduled_date."""
    sd = parse_date(scheduled_date)
    start = parse_datetime(start_str)
    end = parse_datetime(end_str)
    if end - start != timedelta(minutes=90):
        raise_error(ERR_INVALID_REQUEST,
                    "dawn_window_end must be exactly 90 minutes after dawn_window_start")
    if start.date() != sd:
        raise_error(ERR_INVALID_REQUEST,
                    "dawn_window_start date portion must equal scheduled_date")
    return start, end


# ---------------------------------------------------------------------------
# Create / list / read
# ---------------------------------------------------------------------------

@bp.post("/flights")
def create_flight():
    authorized(["OperationsManager"])
    body = get_body()
    scheduled_date = req_date(body, "scheduled_date")
    dawn_start = req_datetime(body, "dawn_window_start")
    dawn_end = req_datetime(body, "dawn_window_end")
    launch_site_id = req_str(body, "launch_site_id")
    balloon_id = req_str(body, "balloon_id")
    pilot_id = req_str(body, "pilot_id")
    kind = req_enum(body, "kind", ("SHARED", "CHARTER"))
    fuel_lbs = opt_int(body, "fuel_lbs", default=200, minimum=0)
    _validate_dawn_window(scheduled_date, dawn_start, dawn_end)
    # Body references must resolve
    if launch_site_id not in db["launch_sites"]:
        raise_error(ERR_NOT_FOUND, f"launch site not found: {launch_site_id}")
    if balloon_id not in db["balloons"]:
        raise_error(ERR_NOT_FOUND, f"balloon not found: {balloon_id}")
    if pilot_id not in db["pilots"]:
        raise_error(ERR_NOT_FOUND, f"pilot not found: {pilot_id}")
    rec = new_record("flights", {
        "scheduled_date": scheduled_date,
        "dawn_window_start": fmt_datetime(parse_datetime(dawn_start)),
        "dawn_window_end": fmt_datetime(parse_datetime(dawn_end)),
        "launch_site_id": launch_site_id,
        "balloon_id": balloon_id,
        "pilot_id": pilot_id,
        "kind": kind,
        "fuel_lbs": fuel_lbs,
        "status": "DRAFT",
        "weather_decision": "NONE",
        "weather_decision_at": None,
        "cancel_reason": None,
        "duration_hours": None,
    })
    return success_object(public_flight(rec), status=201)


@bp.get("/flights")
def list_flights():
    authorized(ALL_READ_ROLES)
    items = list(db["flights"].values())
    for field in ("launch_site_id", "balloon_id", "pilot_id", "status"):
        value = request.args.get(field)
        if value is not None:
            items = [f for f in items if f.get(field) == value]
    items = sort_created(items)
    total = len(items)
    limit, offset = get_pagination()
    page = items[offset:offset + limit]
    return success_list([public_flight(f) for f in page], total, limit, offset)


@bp.get("/flights/<flight_id>")
def get_flight(flight_id):
    authorized(ALL_READ_ROLES)
    rec = require_path_resource("flights", flight_id, "flight")
    return success_object(public_flight(rec))


# ---------------------------------------------------------------------------
# Publish precondition battery (PRD 3.2, evaluated in the PRD's order:
# site permission → aircraft readiness → pilot currency → balloon schedule →
# pilot schedule)
# ---------------------------------------------------------------------------

def _check_publish_battery(flight):
    site = db["launch_sites"].get(flight["launch_site_id"])
    if (site is None or site["permission_status"] != "GRANTED"
            or site["permission_expires_on"] < flight["scheduled_date"]):
        raise_error(ERR_SITE_PERMISSION_NOT_GRANTED,
                    "launch site permission is not GRANTED or lapses before scheduled_date")
    balloon = db["balloons"].get(flight["balloon_id"])
    if (balloon is None or balloon["status"] != "ACTIVE"
            or balloon["inspection_due_on"] is None
            or balloon["inspection_due_on"] < flight["scheduled_date"]):
        raise_error(ERR_BALLOON_GROUNDED,
                    "balloon is not ACTIVE or its inspection is not current for scheduled_date")
    pilot = db["pilots"].get(flight["pilot_id"])
    if pilot is None or compute_currency(pilot)["currency_status"] != "CURRENT":
        raise_error(ERR_PILOT_NOT_CURRENT, "pilot currency_status is EXPIRED")


def _check_schedule_conflicts(flight, scheduled_date, start, end):
    """Half-open [start, end) balloon overlap; whole-date pilot conflict."""
    for o in db["flights"].values():
        if o["id"] == flight["id"] or o["status"] not in ACTIVE_FLIGHT_STATES:
            continue
        if o["balloon_id"] == flight["balloon_id"]:
            os_ = parse_datetime(o["dawn_window_start"])
            oe = parse_datetime(o["dawn_window_end"])
            if start < oe and os_ < end:
                raise_error(ERR_BALLOON_SCHEDULE_CONFLICT,
                            "balloon already committed to an overlapping dawn window")
        if o["pilot_id"] == flight["pilot_id"] and o["scheduled_date"] == scheduled_date:
            raise_error(ERR_PILOT_SCHEDULE_CONFLICT,
                        "pilot already committed to a flight on the same scheduled_date")


# ---------------------------------------------------------------------------
# Flight lifecycle events
# ---------------------------------------------------------------------------

@bp.post("/flights/<flight_id>/events")
def flight_events(flight_id):
    caller = authorized(["OperationsManager", "Pilot"])
    # Priority 2: event-to-role slice segregation (before existence/body)
    check_event_slice(caller, peek_event_type(), EVENT_SLICES)
    flight = require_path_resource("flights", flight_id, "flight")
    body = get_body()
    event_type = req_str(body, "event_type")
    if event_type not in ALL_EVENTS:
        raise_error(ERR_INVALID_REQUEST, f"unknown event_type: {event_type}")

    if event_type == "PUBLISH":
        if flight["status"] != "DRAFT":
            raise_error(ERR_INVALID_STATE, f"cannot PUBLISH from {flight['status']}")
        _check_publish_battery(flight)
        _check_schedule_conflicts(
            flight, flight["scheduled_date"],
            parse_datetime(flight["dawn_window_start"]),
            parse_datetime(flight["dawn_window_end"]))
        flight["status"] = "SCHEDULED"
        touch(flight)
        return success_object(public_flight(flight))

    if event_type == "RESCHEDULE":
        # Priority 4 body shape: new date + window, exactly 90 min, on the date
        new_date = req_date(body, "new_scheduled_date")
        new_start_s = req_datetime(body, "new_dawn_window_start")
        new_end_s = req_datetime(body, "new_dawn_window_end")
        new_start, new_end = _validate_dawn_window(new_date, new_start_s, new_end_s)
        if flight["status"] != "NO_GO":
            raise_error(ERR_INVALID_STATE, f"cannot RESCHEDULE from {flight['status']}")
        _check_schedule_conflicts(flight, new_date, new_start, new_end)
        flight["scheduled_date"] = new_date
        flight["dawn_window_start"] = fmt_datetime(new_start)
        flight["dawn_window_end"] = fmt_datetime(new_end)
        flight["weather_decision"] = "NONE"
        flight["weather_decision_at"] = None
        flight["status"] = "SCHEDULED"
        touch(flight)
        return success_object(public_flight(flight))

    if event_type == "CANCEL":
        if flight["status"] == "SCHEDULED":
            cancel_flight_cascade(flight, "OPERATOR", "OPERATOR_CANCEL", with_goodwill=True)
        elif flight["status"] == "NO_GO":
            cancel_flight_cascade(flight, "WEATHER", "WEATHER_CANCEL", with_goodwill=False)
        else:
            raise_error(ERR_INVALID_STATE, f"cannot CANCEL from {flight['status']}")
        return success_object(public_flight(flight))

    if event_type == "CLOSE":
        if flight["status"] != "LANDED":
            raise_error(ERR_INVALID_STATE, f"cannot CLOSE from {flight['status']}")
        for a in db["chase_assignments"].values():
            if a["flight_id"] == flight["id"] and a["status"] not in ("RECOVERED", "DEBRIEFED"):
                raise_error(ERR_INVALID_STATE,
                            "every chase assignment must be RECOVERED or DEBRIEFED before CLOSE")
        for r in db["reservations"].values():
            if r["flight_id"] == flight["id"] and r["booking_status"] == "CHECKED_IN":
                raise_error(ERR_INVALID_STATE,
                            "every CHECKED_IN reservation must be advanced to FLOWN (or CANCELLED) before CLOSE")
        flight["status"] = "CLOSED"
        touch(flight)
        return success_object(public_flight(flight))

    # ---- Pilot-scoped events: ownership (priority 6) before state (7) ----
    if flight["pilot_id"] != caller.user_id:
        raise_error(ERR_FLIGHT_NOT_ASSIGNED,
                    "acting pilot does not match flight.pilot_id")

    if event_type == "ENTER_WEATHER_REVIEW":
        if flight["status"] != "SCHEDULED":
            raise_error(ERR_INVALID_STATE,
                        f"cannot ENTER_WEATHER_REVIEW from {flight['status']}")
        now = CLOCK.now()
        if not (parse_datetime(flight["dawn_window_start"]) <= now
                <= parse_datetime(flight["dawn_window_end"])):
            raise_error(ERR_DAWN_WINDOW_EXPIRED,
                        "weather review is only permitted inside the dawn window (inclusive)")
        flight["status"] = "WEATHER_REVIEW"
        touch(flight)
        return success_object(public_flight(flight))

    if event_type == "RECORD_GO":
        if flight["status"] != "WEATHER_REVIEW":
            raise_error(ERR_INVALID_STATE, f"cannot RECORD_GO from {flight['status']}")
        # Weather-limits check is evaluated before the dawn-window check (PRD 3.5)
        briefing = latest_recorded_briefing(flight["id"])
        if briefing is None or briefing["decision"] != "GO":
            raise_error(ERR_WEATHER_LIMITS_EXCEEDED,
                        "latest RECORDED briefing does not carry a GO decision")
        if CLOCK.now() > parse_datetime(flight["dawn_window_end"]):
            raise_error(ERR_DAWN_WINDOW_EXPIRED, "dawn window has closed")
        flight["weather_decision"] = "GO"
        flight["weather_decision_at"] = CLOCK.now_iso()
        flight["status"] = "CLEARED_FOR_LAUNCH"
        touch(flight)
        return success_object(public_flight(flight))

    if event_type == "RECORD_NO_GO":
        if flight["status"] != "WEATHER_REVIEW":
            raise_error(ERR_INVALID_STATE, f"cannot RECORD_NO_GO from {flight['status']}")
        flight["weather_decision"] = "NO_GO"
        flight["weather_decision_at"] = CLOCK.now_iso()
        flight["status"] = "NO_GO"
        touch(flight)
        return success_object(public_flight(flight))

    if event_type == "LAUNCH":
        if flight["status"] != "CLEARED_FOR_LAUNCH":
            raise_error(ERR_INVALID_STATE, f"cannot LAUNCH from {flight['status']}")
        # Chase-readiness (business_safety) is evaluated before the window check
        ready = any(
            a["flight_id"] == flight["id"] and a["status"] in ("ASSIGNED", "EN_ROUTE")
            for a in db["chase_assignments"].values())
        if not ready:
            raise_error(ERR_CHASE_NOT_READY,
                        "no chase assignment in ASSIGNED or EN_ROUTE for this flight")
        if CLOCK.now() > parse_datetime(flight["dawn_window_end"]):
            raise_error(ERR_DAWN_WINDOW_EXPIRED, "dawn window has closed")
        balloon = db["balloons"].get(flight["balloon_id"])
        if balloon is not None and flight_payload_used(flight) > balloon["max_gross_weight_lbs"]:
            raise_error(ERR_PAYLOAD_EXCEEDED, "payload exceeds balloon max gross weight")
        flight["status"] = "AIRBORNE"
        touch(flight)
        return success_object(public_flight(flight))

    if event_type == "LAND":
        if flight["status"] != "AIRBORNE":
            raise_error(ERR_INVALID_STATE, f"cannot LAND from {flight['status']}")
        duration = opt_number(body, "duration_hours", default=None, minimum=0)
        flight["duration_hours"] = duration
        flight["status"] = "LANDED"
        touch(flight)
        return success_object(public_flight(flight))

    raise_error(ERR_INVALID_REQUEST, f"unknown event_type: {event_type}")


# ---------------------------------------------------------------------------
# Launch-site selection (PRD 3.3) — OCC guarded by expected_flight_version
# ---------------------------------------------------------------------------

@bp.post("/flights/<flight_id>/select-launch-site")
def select_launch_site(flight_id):
    authorized(["OperationsManager"])
    flight = require_path_resource("flights", flight_id, "flight")
    body = get_body()
    expected = body.get("expected_flight_version")
    if expected is None or isinstance(expected, bool) or not isinstance(expected, int):
        raise_error(ERR_INVALID_REQUEST,
                    "expected_flight_version is required and must be an integer")
    new_site_id = body.get("launch_site_id")
    if new_site_id is not None and not isinstance(new_site_id, str):
        raise_error(ERR_INVALID_REQUEST, "launch_site_id must be a string")
    if new_site_id is not None and new_site_id not in db["launch_sites"]:
        raise_error(ERR_NOT_FOUND, f"launch site not found: {new_site_id}")
    # Priority 5: optimistic concurrency
    if expected != flight["version"]:
        raise_error(ERR_STALE_VERSION,
                    f"expected_flight_version {expected} does not match current "
                    f"version {flight['version']}")
    if flight["status"] not in ("SCHEDULED", "WEATHER_REVIEW"):
        raise_error(ERR_INVALID_STATE,
                    f"cannot select launch site while flight is {flight['status']}")
    if new_site_id is not None:
        site = db["launch_sites"][new_site_id]
        if (site["permission_status"] != "GRANTED"
                or site["permission_expires_on"] < flight["scheduled_date"]):
            raise_error(ERR_SITE_PERMISSION_NOT_GRANTED,
                        "launch site permission is not GRANTED or lapses before scheduled_date")
    else:
        new_site_id = select_site_or_raise(flight)
    flight["launch_site_id"] = new_site_id
    touch(flight)
    return success_object(public_flight(flight))


@bp.get("/flights/<flight_id>/site-candidates")
def get_site_candidates(flight_id):
    caller = authorized(["OperationsManager", "Pilot"])
    flight = require_path_resource("flights", flight_id, "flight")
    # The read model is available to the operations desk and the assigned pilot
    if caller.role == "Pilot" and flight["pilot_id"] != caller.user_id:
        raise_error(ERR_FLIGHT_NOT_ASSIGNED,
                    "acting pilot does not match flight.pilot_id")
    rows = site_candidates(flight)
    data = [{
        "site_id": r["site_id"],
        "wind_margin_kts": r["wind_margin_kts"],
        "permission_granted_at": r["permission_granted_at"],
    } for r in rows]
    total = len(data)
    limit, offset = get_pagination()
    page = data[offset:offset + limit]
    return success_list(page, total, limit, offset)
