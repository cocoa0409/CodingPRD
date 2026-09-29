"""Site inspection endpoints (PRD section 3.3)."""
from datetime import timedelta

from flask import Blueprint

import clock
import db as store
import enums
import lookup
import middleware
import response
import serializers
import validate
from db import db, touch
from errors import ApiError
from services import rollups

bp = Blueprint("inspections", __name__)

OCCUPYING_STATUSES = ("PLANNED", "COMPLETED")


@bp.route("/sourcing/site-inspections", methods=["POST"])
@middleware.roles(middleware.ROLE_SOURCING_MANAGER)
def plan_inspection():
    data = validate.body()

    raw_entry_id = data.get("shortlist_entry_id")
    entry = None
    if raw_entry_id is not None:
        if not isinstance(raw_entry_id, str):
            validate.bad("Field shortlist_entry_id must be a string")
        entry = lookup.entry(raw_entry_id)

    validate.req_str(data, "shortlist_entry_id")
    inspector_user_id = validate.req_str(data, "inspector_user_id")
    window_start = validate.req_instant(data, "window_start")
    window_end = validate.req_instant(data, "window_end")
    travel_buffer_minutes = validate.opt_int(data, "travel_buffer_minutes",
                                             minimum=0, maximum=720, default=90)

    if window_end <= window_start:
        raise ApiError("ERR_INVALID_INSPECTION_WINDOW",
                       "window_end must be strictly after window_start")

    if entry["status"] != "SHORTLISTED":
        raise ApiError("ERR_SHORTLIST_ENTRY_NOT_SHORTLISTED",
                       "The shortlist entry is not in SHORTLISTED")

    venue = db.venues[entry["venue_id"]]
    if venue["preferred_supplier_status"] == "SUSPENDED":
        raise ApiError("ERR_VENUE_SUSPENDED", "The venue is suspended")

    event = db.events[entry["event_id"]]
    event_start = clock.day_start(event["start_date"])
    event_end = clock.day_end(event["end_date"])
    if window_start <= event_end and window_end >= event_start:
        raise ApiError("ERR_INSPECTION_WINDOW_OVERLAPS_EVENT",
                       "The inspection window overlaps the meeting dates")

    occupied_until = window_end + timedelta(minutes=travel_buffer_minutes)
    for other in lookup.inspections_of_venue(venue["id"]):
        if other["status"] not in OCCUPYING_STATUSES:
            continue
        if window_start < other["occupied_until"] and other["window_start"] < occupied_until:
            raise ApiError("ERR_INSPECTION_WINDOW_CONFLICT",
                           "The buffered occupation interval is already taken")

    row = store.base_row()
    row.update({
        "shortlist_entry_id": entry["id"],
        "venue_id": venue["id"],
        "inspector_user_id": inspector_user_id,
        "window_start": window_start,
        "window_end": window_end,
        "travel_buffer_minutes": travel_buffer_minutes,
        "occupied_until": occupied_until,
        "status": "PLANNED",
        "findings_score": None,
        "cancel_reason": None,
    })
    db.inspections[row["id"]] = row

    entry["status"] = "INSPECTION_SCHEDULED"
    rollups.refresh_inspection_count(entry)
    touch(entry)
    return response.obj(serializers.inspection(row), 201)


@bp.route("/sourcing/site-inspections/<inspection_id>/complete", methods=["POST"])
@middleware.roles(middleware.ROLE_SOURCING_MANAGER)
def complete_inspection(inspection_id):
    inspection = lookup.inspection(inspection_id)
    data = validate.body()
    findings_score = validate.req_int(data, "findings_score", minimum=1, maximum=5)

    if inspection["status"] != "PLANNED":
        raise ApiError("ERR_INSPECTION_STATE_INVALID",
                       "Only a PLANNED inspection may be completed")
    if clock.now() < inspection["window_end"]:
        raise ApiError("ERR_INSPECTION_STATE_INVALID",
                       "The inspection window has not elapsed yet")

    inspection["status"] = "COMPLETED"
    inspection["findings_score"] = findings_score
    touch(inspection)

    entry = db.entries.get(inspection["shortlist_entry_id"])
    if entry is not None:
        if entry["status"] == "INSPECTION_SCHEDULED":
            entry["status"] = "INSPECTED"
        rollups.refresh_inspection_count(entry)
        touch(entry)
    return response.obj(serializers.inspection(inspection))


@bp.route("/sourcing/site-inspections/<inspection_id>/cancel", methods=["POST"])
@middleware.roles(middleware.ROLE_SOURCING_MANAGER)
def cancel_inspection(inspection_id):
    inspection = lookup.inspection(inspection_id)
    data = validate.body()
    cancel_reason = validate.req_str(data, "cancel_reason")

    if inspection["status"] != "PLANNED":
        raise ApiError("ERR_INSPECTION_STATE_INVALID",
                       "Only a PLANNED inspection may be cancelled")

    inspection["status"] = "CANCELLED"
    inspection["cancel_reason"] = cancel_reason
    touch(inspection)

    entry = db.entries.get(inspection["shortlist_entry_id"])
    if entry is not None:
        rollups.refresh_inspection_count(entry)
        if entry["inspection_count"] == 0 and entry["status"] == "INSPECTION_SCHEDULED":
            entry["status"] = "SHORTLISTED"
        touch(entry)
    return response.obj(serializers.inspection(inspection))


@bp.route("/sourcing/site-inspections/<inspection_id>", methods=["GET"])
@middleware.roles(*middleware.PLANNER_SIDE)
def get_inspection(inspection_id):
    return response.obj(serializers.inspection(lookup.inspection(inspection_id)))


@bp.route("/sourcing/site-inspections", methods=["GET"])
@middleware.roles(*middleware.PLANNER_SIDE)
def list_inspections():
    status = validate.enum_filter("status", enums.INSPECTION_STATUSES)
    shortlist_entry_id = validate.str_filter("shortlist_entry_id")
    venue_id = validate.str_filter("venue_id")
    inspector_user_id = validate.str_filter("inspector_user_id")
    limit, offset = validate.pagination()
    rows = store.ordered(db.inspections.values())
    if status:
        rows = [r for r in rows if r["status"] == status]
    if shortlist_entry_id:
        rows = [r for r in rows if r["shortlist_entry_id"] == shortlist_entry_id]
    if venue_id:
        rows = [r for r in rows if r["venue_id"] == venue_id]
    if inspector_user_id:
        rows = [r for r in rows if r["inspector_user_id"] == inspector_user_id]
    return validate.page(rows, limit, offset, serializers.inspection)
