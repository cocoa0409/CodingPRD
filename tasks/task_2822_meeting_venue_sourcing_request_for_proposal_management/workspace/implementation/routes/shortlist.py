"""Venue shortlist entry endpoints (PRD section 3.2)."""
from flask import Blueprint

import db as store
import enums
import lookup
import middleware
import response
import serializers
import validate
from db import db, touch
from errors import ApiError
from services import flows, rollups

bp = Blueprint("shortlist", __name__)

ENTRY_CREATE_EVENT_STATUSES = ("REQUIREMENTS_LOCKED", "SOURCING", "BID_REVIEW")


@bp.route("/sourcing/events/<event_id>/shortlist-entries", methods=["POST"])
@middleware.roles(middleware.ROLE_SOURCING_MANAGER)
def create_entry(event_id):
    event = lookup.event(event_id)
    data = validate.body()

    raw_venue_id = data.get("venue_id")
    venue = None
    if raw_venue_id is not None:
        if not isinstance(raw_venue_id, str):
            validate.bad("Field venue_id must be a string")
        venue = lookup.venue(raw_venue_id)

    validate.req_str(data, "venue_id")
    rank_seq = validate.req_int(data, "rank_seq", minimum=1)
    inspection_required = validate.opt_bool(data, "inspection_required", False)

    for existing in lookup.entries_of_event(event["id"]):
        if existing["venue_id"] == venue["id"] or existing["rank_seq"] == rank_seq:
            raise ApiError(
                "ERR_VENUE_ALREADY_SHORTLISTED",
                "This venue or rank_seq is already used inside the event",
            )

    if event["status"] not in ENTRY_CREATE_EVENT_STATUSES:
        raise ApiError("ERR_EVENT_STATE_INVALID",
                       "The event does not admit new shortlist entries")

    if venue["preferred_supplier_status"] == "SUSPENDED":
        raise ApiError("ERR_VENUE_SUSPENDED", "The venue is suspended")

    if venue["largest_space_sqft"] < event["largest_meeting_space_sqft"]:
        raise ApiError("ERR_VENUE_SPACE_INSUFFICIENT",
                       "The venue cannot host the required general session")

    row = store.base_row()
    row.update({
        "event_id": event["id"],
        "venue_id": venue["id"],
        "rank_seq": rank_seq,
        "inspection_required": inspection_required,
        "status": "CANDIDATE",
        "program_status_at_shortlist": (
            "IN_PROGRAM"
            if venue["preferred_supplier_status"] in enums.IN_PROGRAM_STATUSES
            else "OUT_OF_PROGRAM"
        ),
        "elimination_reason": None,
        "inspection_count": 0,
    })
    db.entries[row["id"]] = row

    rollups.refresh_shortlisted_count(event)
    touch(event)
    return response.obj(serializers.entry(row), 201)


@bp.route("/sourcing/shortlist-entries/<entry_id>/shortlist", methods=["POST"])
@middleware.roles(middleware.ROLE_SOURCING_MANAGER)
def promote_entry(entry_id):
    entry = lookup.entry(entry_id)
    event = db.events[entry["event_id"]]
    venue = db.venues[entry["venue_id"]]

    if event["status"] not in ENTRY_CREATE_EVENT_STATUSES:
        raise ApiError("ERR_EVENT_STATE_INVALID",
                       "The event does not admit shortlist promotion")
    if entry["status"] != "CANDIDATE":
        raise ApiError("ERR_SHORTLIST_ENTRY_STATE_INVALID",
                       "Only a CANDIDATE entry may be promoted")
    if venue["preferred_supplier_status"] == "SUSPENDED":
        raise ApiError("ERR_VENUE_SUSPENDED", "The venue is suspended")
    if event["preferred_program_only"] and (
            entry["program_status_at_shortlist"] != "IN_PROGRAM"):
        raise ApiError("ERR_PREFERRED_PROGRAM_REQUIRED",
                       "This event admits preferred-program venues only")

    entry["status"] = "SHORTLISTED"
    touch(entry)
    rollups.refresh_shortlisted_count(event)
    touch(event)
    return response.obj(serializers.entry(entry))


@bp.route("/sourcing/shortlist-entries/<entry_id>/eliminate", methods=["POST"])
@middleware.roles(middleware.ROLE_SOURCING_MANAGER)
def eliminate(entry_id):
    entry = lookup.entry(entry_id)
    event = db.events[entry["event_id"]]
    data = validate.body()
    reason = validate.req_str(data, "elimination_reason")

    if entry["status"] in ("AWARDED", "ELIMINATED"):
        raise ApiError("ERR_SHORTLIST_ENTRY_STATE_INVALID",
                       "This entry is already in a terminal state")

    flows.eliminate_entry(entry, reason)
    rollups.refresh_shortlisted_count(event)
    touch(event)
    return response.obj(serializers.entry(entry))


@bp.route("/sourcing/shortlist-entries/<entry_id>", methods=["GET"])
@middleware.roles(*middleware.PLANNER_SIDE)
def get_entry(entry_id):
    return response.obj(serializers.entry(lookup.entry(entry_id)))


@bp.route("/sourcing/shortlist-entries", methods=["GET"])
@middleware.roles(*middleware.PLANNER_SIDE)
def list_entries():
    status = validate.enum_filter("status", enums.ENTRY_STATUSES)
    event_id = validate.str_filter("event_id")
    venue_id = validate.str_filter("venue_id")
    limit, offset = validate.pagination()
    rows = store.ordered(db.entries.values())
    if status:
        rows = [r for r in rows if r["status"] == status]
    if event_id:
        rows = [r for r in rows if r["event_id"] == event_id]
    if venue_id:
        rows = [r for r in rows if r["venue_id"] == venue_id]
    return validate.page(rows, limit, offset, serializers.entry)
