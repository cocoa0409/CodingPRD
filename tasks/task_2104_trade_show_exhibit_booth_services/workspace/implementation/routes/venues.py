"""Venues and their union jurisdictions (PRD §3.1)."""
from flask import Blueprint

import db
import response
from middleware import ANY_ROLE, require_roles
from validation import json_body, require_row

bp = Blueprint("venues", __name__)
store = db.store

TRADES = ("RIGGING", "ELECTRICAL", "CARPENTRY", "MATERIAL_HANDLING", "CLEANING")
BOOTH_TYPES = ("INLINE", "CORNER", "PENINSULA", "ISLAND")


@bp.post("/venues")
def create_venue():
    require_roles("ShowOperations")
    body = json_body()
    name = body.string("name")
    city = body.string("city")
    st_start = body.hhmm("straight_time_start_hhmm", required=False, default="08:00")
    st_end = body.hhmm("straight_time_end_hhmm", required=False, default="16:30")
    forklift = body.integer("max_forklift_capacity_lbs", required=False, default=6000)
    sign_types = body.string_array("hanging_sign_booth_types", required=False,
                                   default=["ISLAND", "PENINSULA"])
    for value in sign_types:
        if value not in BOOTH_TYPES:
            from errors import ApiError
            raise ApiError("ERR_INVALID_REQUEST",
                           "hanging_sign_booth_types must contain booth types")
    dock_count = body.integer("dock_count", required=False, default=4)
    status = body.enum("status", ("ACTIVE", "INACTIVE"), required=False, default="ACTIVE")

    venue = {
        "id": db.new_id(),
        "name": name,
        "city": city,
        "straight_time_start_hhmm": st_start,
        "straight_time_end_hhmm": st_end,
        "max_forklift_capacity_lbs": forklift,
        "hanging_sign_booth_types": list(sign_types),
        "dock_count": dock_count,
        "status": status,
    }
    db.stamp_common(venue)
    store.venues[venue["id"]] = venue
    return response.created(venue)


@bp.get("/venues/<venue_id>")
def get_venue(venue_id):
    require_roles(ANY_ROLE)
    venue = require_row(store.venues, venue_id, "ERR_VENUE_NOT_FOUND", "Venue")
    return response.ok(venue)


@bp.post("/venues/<venue_id>/union-jurisdictions")
def create_jurisdiction(venue_id):
    require_roles("ShowOperations")
    body = json_body()
    trade = body.enum("trade", TRADES)
    rate = body.integer("straight_time_rate_cents_per_hour")
    overtime = body.number("overtime_multiplier", required=False, default=1.5)
    doubletime = body.number("doubletime_multiplier", required=False, default=2.0)
    min_call = body.number("min_call_hours", required=False, default=4.0)
    crew_max = body.integer("crew_max_size", required=False, default=8)
    self_install = body.boolean("exhibitor_self_install_allowed", required=False,
                                default=False)
    buffer_minutes = body.integer("turnaround_buffer_minutes", required=False, default=30)

    require_row(store.venues, venue_id, "ERR_VENUE_NOT_FOUND", "Venue")

    jurisdiction = {
        "id": db.new_id(),
        "venue_id": venue_id,
        "trade": trade,
        "straight_time_rate_cents_per_hour": rate,
        "overtime_multiplier": overtime,
        "doubletime_multiplier": doubletime,
        "min_call_hours": min_call,
        "crew_max_size": crew_max,
        "exhibitor_self_install_allowed": self_install,
        "turnaround_buffer_minutes": buffer_minutes,
    }
    db.stamp_common(jurisdiction)
    store.jurisdictions[jurisdiction["id"]] = jurisdiction
    return response.created(jurisdiction)


@bp.get("/venues/<venue_id>/union-jurisdictions")
def list_jurisdictions(venue_id):
    require_roles(ANY_ROLE)
    response.pagination_params()
    require_row(store.venues, venue_id, "ERR_VENUE_NOT_FOUND", "Venue")
    rows = [j for j in store.jurisdictions.values() if j["venue_id"] == venue_id]
    rows = response.filter_rows(rows, "trade")
    return response.listing(rows)
