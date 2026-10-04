"""VendorBriefing endpoints (PRD 3.8)."""

from datetime import timedelta

from flask import Blueprint, request

from db import db, serialize
from errors import ApiError, bad_request, invalid_state, unauthorized
from middleware import (
    authenticate,
    body,
    enum,
    require_str,
)
from response import ok, ok_list
from services import routing, state
from timeutil import parse_dt
from routes._common import page_of, require_briefing, require_vendor

bp = Blueprint("briefings", __name__)

DURATIONS = (30, 45, 60)
SLOT_BUFFER_MINUTES = 15
OPEN_STATUSES = ("SCHEDULED", "HELD")


@bp.post("/research/vendor-briefings")
def create_briefing():
    authenticate(["VendorRep"])
    data = body()
    vendor_id = require_str(data, "vendor_id")
    briefing_topic = require_str(data, "briefing_topic")
    requested_start = require_str(data, "requested_start_utc")
    start = parse_dt(requested_start)
    if start is None:
        raise bad_request("requested_start_utc must be an ISO 8601 instant.")
    duration = data.get("duration_minutes")
    if isinstance(duration, bool) or not isinstance(duration, int):
        raise bad_request("duration_minutes must be an integer.")
    enum(duration, DURATIONS, "duration_minutes")

    require_vendor(vendor_id)

    winner = routing.briefing_winner(briefing_topic)
    if winner is None:
        raise ApiError(
            "ERR_BRIEFING_SEPARATION_FAILED",
            "No analyst free of a sales tie to this vendor can take the briefing topic.",
            403,
        )

    start_edge = start - timedelta(minutes=SLOT_BUFFER_MINUTES)
    end_edge = start + timedelta(minutes=duration + SLOT_BUFFER_MINUTES)
    for other in db.briefings.values():
        if other.get("analyst_id") != winner["id"]:
            continue
        if other.get("status") not in OPEN_STATUSES:
            continue
        other_start = parse_dt(other.get("requested_start_utc"))
        if other_start is None:
            continue
        other_end = other_start + timedelta(minutes=other.get("duration_minutes", 0))
        if start_edge < other_end and other_start < end_edge:
            raise ApiError(
                "ERR_BRIEFING_SLOT_CONFLICT",
                "The requested window collides with another briefing of the assigned analyst.",
                409,
            )

    briefing = db.create(
        vendor_id=vendor_id,
        analyst_id=winner["id"],
        briefing_topic=briefing_topic,
        requested_start_utc=start,
        duration_minutes=duration,
        status="SCHEDULED",
        separation_check_result="PASS",
        held_at=None,
    )
    db.briefings[briefing["id"]] = briefing
    return ok(serialize(briefing), 201)


@bp.get("/research/vendor-briefings/<briefing_id>")
def read_briefing(briefing_id):
    authenticate(["VendorRep", "Analyst", "ResearchDirector", "ComplianceOfficer", "PlatformAdmin"])
    return ok(serialize(require_briefing(briefing_id)), 200)


@bp.get("/research/vendor-briefings")
def list_briefings():
    authenticate(["VendorRep", "Analyst", "ResearchDirector", "ComplianceOfficer", "PlatformAdmin"])
    items = list(db.briefings.values())
    vendor_id = request.args.get("vendor_id")
    analyst_id = request.args.get("analyst_id")
    status = request.args.get("status")
    if vendor_id:
        items = [b for b in items if b.get("vendor_id") == vendor_id]
    if analyst_id:
        items = [b for b in items if b.get("analyst_id") == analyst_id]
    if status:
        items = [b for b in items if b.get("status") == status]
    page, limit, offset, total = page_of(items)
    return ok_list(page, limit, offset, total)


@bp.post("/research/vendor-briefings/<briefing_id>/record-briefing")
def record_briefing(briefing_id):
    role, user_id = authenticate(["Analyst", "ResearchDirector"])
    data = body()
    held_at = data.get("held_at")
    decline_reason = data.get("decline_reason")
    if decline_reason is not None and not isinstance(decline_reason, str):
        raise bad_request("decline_reason must be a string.")
    if held_at is not None and not isinstance(held_at, str):
        raise bad_request("held_at must be an ISO 8601 instant.")
    briefing = require_briefing(briefing_id)

    if decline_reason is not None and held_at is None:
        if briefing.get("status") not in ("SCREENED", "SCHEDULED"):
            raise invalid_state("Only a SCREENED or SCHEDULED briefing can be declined.")
        briefing["status"] = "DECLINED"
        db.touch(briefing)
        return ok(serialize(briefing), 200)

    if role == "Analyst" and user_id != briefing.get("analyst_id"):
        raise unauthorized("Only the assigned analyst may record this briefing.")
    if briefing.get("status") != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED briefing can be recorded as held.")
    start = parse_dt(briefing.get("requested_start_utc"))
    if start is None or db.now() < start:
        raise invalid_state("The clock has not yet reached the briefing start instant.")

    briefing["status"] = "HELD"
    briefing["held_at"] = db.now()
    db.touch(briefing)

    vendor_obj = db.vendors.get(briefing.get("vendor_id"))
    if vendor_obj is not None:
        vendor_obj["last_briefing_at"] = db.now()
        state.recompute_vendor_eligibility(vendor_obj)
        db.touch(vendor_obj)
    return ok(serialize(briefing), 200)
