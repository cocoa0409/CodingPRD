"""ConferenceEvent endpoints (PRD 3.9)."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

from db import db, serialize
from errors import ApiError, bad_request, invalid_state
from middleware import authenticate, body, enum, optional_str, require_str
from response import ok
from services import state
from timeutil import parse_dt
from routes._common import require_event, require_vendor

bp = Blueprint("events", __name__)

REGIONS = ("NA", "EMEA", "APAC")
SESSION_KINDS = ("RESEARCH_SESSION", "SPONSOR_KEYNOTE")
SPONSOR_SHARE_CEILING = Decimal("0.4000")
MIN_SESSION_MINUTES = 15


def _instant(data, field):
    value = require_str(data, field)
    parsed = parse_dt(value)
    if parsed is None:
        raise bad_request("Field %s must be an ISO 8601 instant." % field)
    return parsed


def recompute_agenda(event):
    sessions = event.get("sessions") or []
    research = sum(s.get("duration_minutes", 0) for s in sessions if s.get("session_kind") == "RESEARCH_SESSION")
    sponsor = sum(s.get("duration_minutes", 0) for s in sessions if s.get("session_kind") == "SPONSOR_KEYNOTE")
    total = research + sponsor
    share = Decimal("0") if total == 0 else (
        Decimal(sponsor) / Decimal(total)
    ).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    event["research_session_minutes"] = research
    event["sponsor_session_minutes"] = sponsor
    event["sponsor_minute_share"] = float(share)


def _share_after_append(event, row):
    sessions = list(event.get("sessions") or []) + [row]
    total = sum(s.get("duration_minutes", 0) for s in sessions)
    sponsor = sum(s.get("duration_minutes", 0) for s in sessions if s.get("session_kind") == "SPONSOR_KEYNOTE")
    if total == 0:
        return Decimal("0")
    return (Decimal(sponsor) / Decimal(total)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def _platinum_blocks(event, vendor_id):
    """A vendor whose own ACTIVE PLATINUM window covers the event may not keynote."""
    event_start = parse_dt(event.get("start_utc"))
    event_end = parse_dt(event.get("end_utc"))
    if event_start is None or event_end is None:
        return False
    for sponsorship in db.sponsorships.values():
        if sponsorship.get("conference_event_id") != event["id"]:
            continue
        if sponsorship.get("vendor_id") != vendor_id:
            continue
        if sponsorship.get("tier") != "PLATINUM":
            continue
        if sponsorship.get("status") != "ACTIVE":
            continue
        window_start = parse_dt(sponsorship.get("exclusivity_start_utc"))
        window_end = parse_dt(sponsorship.get("exclusivity_end_utc"))
        if window_start is None or window_end is None:
            continue
        if window_start < event_end and event_start < window_end:
            return True
    return False


@bp.post("/research/conference-events")
def create_event():
    authenticate(["EventProgrammer", "PlatformAdmin"])
    data = body()
    event_name = require_str(data, "event_name")
    venue_region = enum(require_str(data, "venue_region"), REGIONS, "venue_region")
    start = _instant(data, "start_utc")
    end = _instant(data, "end_utc")
    event = db.create(
        event_name=event_name,
        venue_region=venue_region,
        start_utc=start,
        end_utc=end,
        status="DRAFT",
        research_session_minutes=0,
        sponsor_session_minutes=0,
        sponsor_minute_share=0.0,
        sponsorship_revenue_cents=0,
        agenda_locked_at=None,
        sessions=[],
    )
    db.events[event["id"]] = event
    return ok(serialize(event), 201)


@bp.get("/research/conference-events/<event_id>")
def read_event(event_id):
    authenticate(["EventProgrammer", "PlatformAdmin", "ResearchDirector", "ComplianceOfficer"])
    event = require_event(event_id)
    state.evaluate_event(event)
    return ok(serialize(event), 200)


@bp.post("/research/conference-events/<event_id>/sessions")
def append_session(event_id):
    authenticate(["EventProgrammer"])
    data = body()
    session_title = require_str(data, "session_title")
    session_kind = enum(require_str(data, "session_kind"), SESSION_KINDS, "session_kind")
    duration = data.get("duration_minutes")
    if isinstance(duration, bool) or not isinstance(duration, int):
        raise bad_request("duration_minutes must be an integer.")
    if duration < MIN_SESSION_MINUTES:
        raise bad_request("duration_minutes must be an integer of at least 15.")
    sponsor_vendor_id = optional_str(data, "sponsor_vendor_id", "")
    event = require_event(event_id)
    if sponsor_vendor_id:
        require_vendor(sponsor_vendor_id)

    status = event.get("status")
    if status in ("COMPLETED", "CANCELLED"):
        raise invalid_state("A terminal event accepts no further agenda rows.")
    if status == "AGENDA_LOCKED" and session_kind != "RESEARCH_SESSION":
        raise ApiError(
            "ERR_AGENDA_LOCKED",
            "Only a RESEARCH_SESSION row may reopen a locked agenda.",
            409,
        )

    row = {
        "session_title": session_title,
        "session_kind": session_kind,
        "duration_minutes": duration,
        "sponsor_vendor_id": sponsor_vendor_id or None,
    }

    if session_kind == "SPONSOR_KEYNOTE" and sponsor_vendor_id:
        if _platinum_blocks(event, sponsor_vendor_id):
            raise ApiError(
                "ERR_SPONSOR_EXCLUSIVITY_OVERLAP",
                "The vendor holds an ACTIVE PLATINUM window covering this event.",
                409,
            )

    if _share_after_append(event, row) > SPONSOR_SHARE_CEILING:
        raise ApiError(
            "ERR_SPONSOR_SHARE_EXCEEDED",
            "Appending the row would push sponsor_minute_share above 0.4000.",
            409,
        )

    event.setdefault("sessions", []).append(row)
    if status == "DRAFT":
        event["status"] = "PROGRAMMING"
    elif status == "AGENDA_LOCKED":
        event["status"] = "PROGRAMMING"
    recompute_agenda(event)
    db.touch(event)
    return ok(serialize(event), 200)


@bp.post("/research/conference-events/<event_id>/lock-agenda")
def lock_agenda(event_id):
    authenticate(["EventProgrammer", "ResearchDirector"])
    event = require_event(event_id)
    if event.get("status") != "PROGRAMMING":
        raise invalid_state("Only a PROGRAMMING event can lock its agenda.")
    if not any(
        s.get("session_kind") == "RESEARCH_SESSION" for s in (event.get("sessions") or [])
    ):
        raise invalid_state("The agenda needs at least one RESEARCH_SESSION before it locks.")
    event["status"] = "AGENDA_LOCKED"
    event["agenda_locked_at"] = db.now()
    db.touch(event)
    return ok(serialize(event), 200)
