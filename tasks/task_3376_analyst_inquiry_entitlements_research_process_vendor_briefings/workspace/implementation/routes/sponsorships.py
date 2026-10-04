"""Sponsorship endpoints (PRD 3.9)."""

from flask import Blueprint, request

from db import db, serialize
from errors import ApiError, bad_request, invalid_state
from middleware import authenticate, body, enum, optional_str, require_str
from response import ok, ok_list
from timeutil import parse_dt
from routes._common import page_of, require_event, require_sponsorship, require_vendor

bp = Blueprint("sponsorships", __name__)

TIERS = ("PLATINUM", "GOLD", "SILVER")
EVENT_OPEN_STATUSES = ("DRAFT", "PROGRAMMING")


def _instant(data, field):
    value = require_str(data, field)
    parsed = parse_dt(value)
    if parsed is None:
        raise bad_request("Field %s must be an ISO 8601 instant." % field)
    return parsed


def _platinum_overlap(event_id, window_start, window_end):
    for other in db.sponsorships.values():
        if other.get("conference_event_id") != event_id:
            continue
        if other.get("tier") != "PLATINUM" or other.get("status") != "ACTIVE":
            continue
        other_start = parse_dt(other.get("exclusivity_start_utc"))
        other_end = parse_dt(other.get("exclusivity_end_utc"))
        if other_start is None or other_end is None:
            continue
        if window_start < other_end and other_start < window_end:
            return True
    return False


@bp.post("/research/sponsorships")
def create_sponsorship():
    authenticate(["SalesRep", "EventProgrammer"])
    data = body()
    event_id = require_str(data, "conference_event_id")
    vendor_id = require_str(data, "vendor_id")
    tier = enum(require_str(data, "tier"), TIERS, "tier")
    amount = data.get("amount_cents")
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise bad_request("amount_cents must be an integer.")
    if amount < 0:
        raise bad_request("amount_cents must be at least 0.")
    window_start = _instant(data, "exclusivity_start_utc")
    window_end = _instant(data, "exclusivity_end_utc")
    expected_version = data.get("expected_conference_event_version")
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise bad_request("expected_conference_event_version must be an integer.")

    event = require_event(event_id)
    require_vendor(vendor_id)

    if tier == "PLATINUM" and _platinum_overlap(event["id"], window_start, window_end):
        raise ApiError(
            "ERR_SPONSOR_EXCLUSIVITY_OVERLAP",
            "The PLATINUM window overlaps another ACTIVE PLATINUM window on this event.",
            409,
        )

    if expected_version != event.get("version"):
        raise ApiError(
            "ERR_STALE_VERSION",
            "expected_conference_event_version does not match the event's current version.",
            412,
        )

    sponsorship = db.create(
        conference_event_id=event["id"],
        vendor_id=vendor_id,
        tier=tier,
        amount_cents=amount,
        exclusivity_start_utc=window_start,
        exclusivity_end_utc=window_end,
        status="PENDING",
        activated_at=None,
        cancelled_at=None,
        sponsor_slot_counted=False,
    )
    db.sponsorships[sponsorship["id"]] = sponsorship
    db.touch(event)
    return ok(serialize(sponsorship), 201)


@bp.get("/research/sponsorships/<sponsorship_id>")
def read_sponsorship(sponsorship_id):
    authenticate(["SalesRep", "EventProgrammer", "ComplianceOfficer", "PlatformAdmin"])
    return ok(serialize(require_sponsorship(sponsorship_id)), 200)


@bp.get("/research/sponsorships")
def list_sponsorships():
    authenticate(["SalesRep", "EventProgrammer", "ComplianceOfficer", "PlatformAdmin"])
    items = list(db.sponsorships.values())
    event_id = request.args.get("conference_event_id")
    vendor_id = request.args.get("vendor_id")
    status = request.args.get("status")
    if event_id:
        items = [s for s in items if s.get("conference_event_id") == event_id]
    if vendor_id:
        items = [s for s in items if s.get("vendor_id") == vendor_id]
    if status:
        items = [s for s in items if s.get("status") == status]
    page, limit, offset, total = page_of(items)
    return ok_list(page, limit, offset, total)


def _event_is_open(event):
    return event is not None and event.get("status") in EVENT_OPEN_STATUSES


@bp.post("/research/sponsorships/<sponsorship_id>/activate")
def activate_sponsorship(sponsorship_id):
    authenticate(["EventProgrammer", "SalesRep"])
    sponsorship = require_sponsorship(sponsorship_id)
    event = require_event(sponsorship.get("conference_event_id"))

    if sponsorship.get("status") != "PENDING":
        raise invalid_state("Only a PENDING sponsorship can be activated.")
    if not _event_is_open(event):
        raise ApiError(
            "ERR_EVENT_AGENDA_LOCKED",
            "The linked event's agenda is locked; the sponsorship can no longer be activated.",
            409,
        )

    sponsorship["status"] = "ACTIVE"
    sponsorship["activated_at"] = db.now()
    sponsorship["sponsor_slot_counted"] = True
    db.touch(sponsorship)

    event["sponsorship_revenue_cents"] = (
        event.get("sponsorship_revenue_cents", 0) + sponsorship.get("amount_cents", 0)
    )
    db.touch(event)
    return ok(serialize(sponsorship), 200)


@bp.post("/research/sponsorships/<sponsorship_id>/cancel")
def cancel_sponsorship(sponsorship_id):
    authenticate(["EventProgrammer", "ComplianceOfficer"])
    data = body()
    optional_str(data, "cancel_reason", "")
    sponsorship = require_sponsorship(sponsorship_id)
    event = require_event(sponsorship.get("conference_event_id"))

    if sponsorship.get("status") != "ACTIVE":
        raise invalid_state("Only an ACTIVE sponsorship can be cancelled.")
    if not _event_is_open(event):
        raise ApiError(
            "ERR_EVENT_AGENDA_LOCKED",
            "The linked event's agenda is locked; the sponsorship can no longer be cancelled.",
            409,
        )

    sponsorship["status"] = "CANCELLED"
    sponsorship["cancelled_at"] = db.now()
    sponsorship["sponsor_slot_counted"] = False
    db.touch(sponsorship)

    event["sponsorship_revenue_cents"] = (
        event.get("sponsorship_revenue_cents", 0) - sponsorship.get("amount_cents", 0)
    )
    db.touch(event)
    return ok(serialize(sponsorship), 200)
