"""In-store event slots: scheduling, reading and listing."""

from datetime import timedelta

from flask import Blueprint

from db import db, now
from errors import fail
from middleware import require
from response import envelope, paginate
from services.core import get_store, new_record, touch
from utils import body, list_params, matches, out, require_fields

bp = Blueprint("store_events", __name__)


def resolve_window(days_from_default_clock, duration_hours, start_offset_hours):
    start = (now()
             + timedelta(days=float(days_from_default_clock))
             + timedelta(hours=float(start_offset_hours or 0)))
    end = start + timedelta(hours=float(duration_hours))
    return start, end


@bp.route("/stores/store-events", methods=["POST"])
def schedule_event():
    require("StoreAssociate")
    payload = body()
    require_fields(payload, "store_id", "event_kind", "title", "capacity_units",
                   "days_from_default_clock", "duration_hours")

    store = get_store(payload["store_id"])

    kind = payload["event_kind"]
    if kind not in ("BUILD_EVENT", "MINI_BUILD"):
        fail("ERR_CONSTRAINT_VIOLATION", "event_kind must be BUILD_EVENT or MINI_BUILD.")

    capacity = int(payload["capacity_units"])
    if capacity < 1:
        fail("ERR_CONSTRAINT_VIOLATION", "capacity_units must be at least 1.")

    start, end = resolve_window(payload["days_from_default_clock"],
                                payload["duration_hours"],
                                payload.get("start_offset_hours"))

    if not start < end:
        fail("ERR_CONSTRAINT_VIOLATION", "The event window must have positive width.")

    # Half-open [start, end): intervals that merely touch are permitted.
    for existing in db().store_events.values():
        if existing["store_id"] != store["id"]:
            continue
        if start < existing["end_utc"] and existing["start_utc"] < end:
            fail("ERR_EVENT_SLOT_OVERLAP",
                 "The requested interval intersects an existing slot of this store.")

    event = new_record({
        "store_id": store["id"],
        "event_kind": kind,
        "title": payload["title"],
        "capacity_units": capacity,
        "start_utc": start,
        "end_utc": end,
        "registered_count": 0,
        "waitlisted_count": 0,
        "waitlist_epoch": 0,
        "event_run_index": store["last_event_run_index"],
        "stage": "SCHEDULED",
    })
    db().store_events[event["id"]] = event
    return envelope(out(event), status=201)


@bp.route("/stores/store-events", methods=["GET"])
def list_events():
    require("StoreAssociate", "Member")
    params = list_params()
    items = [e for e in db().store_events.values()
             if matches(e, params, "store_id", "event_kind", "stage")]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    page, pagination = paginate(items, params)
    return envelope(out(page), response_type="array", pagination=pagination)


@bp.route("/stores/store-events/<event_id>", methods=["GET"])
def read_event(event_id):
    require("StoreAssociate", "Member")
    event = db().store_events.get(event_id)
    if event is None:
        fail("ERR_NOT_FOUND", "No store event exists with id %s." % event_id)
    return envelope(out(event))