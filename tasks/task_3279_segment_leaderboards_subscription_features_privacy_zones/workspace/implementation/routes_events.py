"""Virtual event + RSVP routes."""
from datetime import timedelta
from flask import Blueprint, request

from db import db
from errors import (err_validation, err_not_found, err_unique, err_forbidden,
                    err_invalid_state, err_club_archived, err_window,
                    err_event_overlap, err_inconsistent, err_capacity)
from middleware import require_roles, check_self_or_admin
from response import ok_object, ok_list, init_common, touch, parse_pagination, parse_iso_dt
from serializers import event_view, rsvp_view
from services import lazy_complete_event, logical_now_dt, EVENT_WINDOW_S

bp = Blueprint("events", __name__)


def _get_club_or_404(cid):
    c = db.clubs.get(cid)
    if not c:
        raise err_not_found("Club not found")
    return c


def _is_club_admin(user_id, role, club_id):
    if role == "PlatformAdmin":
        return True
    if role != "Athlete":
        return False
    for m in db.memberships.values():
        if (m["club_id"] == club_id and m["athlete_id"] == user_id
                and m["status"] == "ACTIVE" and m["role"] == "ADMIN"):
            return True
    return False


def _require_club_admin(user_id, role, club_id):
    if not _is_club_admin(user_id, role, club_id):
        raise err_forbidden("Club admin required")


@bp.post("/v1/clubs/<cid>/events")
def create_event(cid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    c = _get_club_or_404(cid)
    _require_club_admin(user_id, role, cid)
    if c["status"] == "ARCHIVED":
        raise err_club_archived()
    body = request.get_json(silent=True) or {}
    name = body.get("name")
    segment_id = body.get("segment_id")
    scheduled_at = body.get("scheduled_at")
    capacity = body.get("capacity")
    if not isinstance(name, str) or not (3 <= len(name) <= 80):
        raise err_validation("name must be 3..80 chars")
    if not isinstance(segment_id, str) or segment_id not in db.segments:
        raise err_validation("segment_id does not reference an existing segment")
    sched = parse_iso_dt(scheduled_at)
    if sched is None:
        raise err_validation("scheduled_at must be ISO8601 UTC")
    if not isinstance(capacity, int) or isinstance(capacity, bool) or not (1 <= capacity <= 500):
        raise err_validation("capacity must be 1..500")
    # temporal window: scheduled strictly in the future
    if not sched > logical_now_dt():
        raise err_window("scheduled_at must be strictly in the future")
    # overlap: half-open [scheduled, scheduled+3600s) vs PUBLISHED events of same club
    new_end = sched + timedelta(seconds=EVENT_WINDOW_S)
    for ev in db.events.values():
        if ev["club_id"] != cid or ev["status"] != "PUBLISHED":
            continue
        ex_start = parse_iso_dt(ev["scheduled_at"])
        ex_end = ex_start + timedelta(seconds=EVENT_WINDOW_S)
        if sched < ex_end and ex_start < new_end:
            raise err_event_overlap()
    # referential consistency: segment ACTIVE and hazard_index == 0
    seg = db.segments[segment_id]
    if seg["status"] != "ACTIVE" or seg.get("hazard_index", 0) != 0:
        raise err_inconsistent("Event segment must be ACTIVE and non-hazardous")
    ev = init_common({
        "club_id": cid,
        "name": name,
        "segment_id": segment_id,
        "scheduled_at": scheduled_at,
        "capacity": capacity,
        "status": "PUBLISHED",
        "rsvp_count": 0,
    })
    db.events[ev["id"]] = ev
    return ok_object(event_view(ev), 201)


@bp.get("/v1/clubs/<cid>/events")
def list_events(cid):
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    _get_club_or_404(cid)
    status_f = request.args.get("status")
    items = [e for e in db.events.values() if e["club_id"] == cid]
    for e in items:
        lazy_complete_event(e)
    if status_f:
        items = [e for e in items if e["status"] == status_f]
    items.sort(key=lambda e: e["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([event_view(e) for e in items], limit, offset)


@bp.get("/v1/events")
def list_events_flat():
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    club_f = request.args.get("club_id")
    seg_f = request.args.get("segment_id")
    status_f = request.args.get("status")
    items = list(db.events.values())
    for e in items:
        lazy_complete_event(e)
    if club_f:
        items = [e for e in items if e["club_id"] == club_f]
    if seg_f:
        items = [e for e in items if e["segment_id"] == seg_f]
    if status_f:
        items = [e for e in items if e["status"] == status_f]
    items.sort(key=lambda e: e["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([event_view(e) for e in items], limit, offset)


@bp.get("/v1/events/<eid>")
def get_event(eid):
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    ev = db.events.get(eid)
    if not ev:
        raise err_not_found("Event not found")
    lazy_complete_event(ev)
    return ok_object(event_view(ev))


@bp.post("/v1/clubs/<cid>/events/<eid>/cancel")
def cancel_event(cid, eid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    _get_club_or_404(cid)
    ev = db.events.get(eid)
    if not ev or ev["club_id"] != cid:
        raise err_not_found("Event not found")
    _require_club_admin(user_id, role, cid)
    c = db.clubs[cid]
    if c["status"] == "ARCHIVED":
        raise err_club_archived()
    if ev["status"] != "PUBLISHED":
        raise err_invalid_state("Only PUBLISHED events may be cancelled")
    ev["status"] = "CANCELLED"
    touch(ev)
    return ok_object(event_view(ev))


# ----------------------------------------------------------------- rsvps ----

@bp.post("/v1/events/<eid>/rsvps")
def create_rsvp(eid):
    require_roles("Athlete", "PlatformAdmin")
    ev = db.events.get(eid)
    if not ev:
        raise err_not_found("Event not found")
    lazy_complete_event(ev)
    body = request.get_json(silent=True) or {}
    athlete_id = body.get("athlete_id")
    if not isinstance(athlete_id, str) or athlete_id not in db.athletes:
        raise err_validation("athlete_id does not reference an existing athlete")
    if ev["status"] != "PUBLISHED":
        raise err_invalid_state("Event is not PUBLISHED")
    sched = parse_iso_dt(ev["scheduled_at"])
    if logical_now_dt() > sched:
        raise err_window("Cannot RSVP after scheduled_at")
    for r in db.rsvps.values():
        if r["event_id"] == eid and r["athlete_id"] == athlete_id:
            raise err_unique("Athlete already holds an RSVP for this event")
    if int(ev["rsvp_count"]) >= int(ev["capacity"]):
        raise err_capacity()
    r = init_common({
        "event_id": eid,
        "athlete_id": athlete_id,
        "status": "GOING",
    })
    db.rsvps[r["id"]] = r
    ev["rsvp_count"] = int(ev["rsvp_count"]) + 1
    touch(ev)
    return ok_object(rsvp_view(r), 201)


@bp.get("/v1/events/<eid>/rsvps")
def list_rsvps(eid):
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    if not db.events.get(eid):
        raise err_not_found("Event not found")
    status_f = request.args.get("status")
    athlete_f = request.args.get("athlete_id")
    items = [r for r in db.rsvps.values() if r["event_id"] == eid]
    if status_f:
        items = [r for r in items if r["status"] == status_f]
    if athlete_f:
        items = [r for r in items if r["athlete_id"] == athlete_f]
    items.sort(key=lambda r: r["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([rsvp_view(r) for r in items], limit, offset)


@bp.get("/v1/rsvps")
def list_rsvps_flat():
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    ev_f = request.args.get("event_id")
    athlete_f = request.args.get("athlete_id")
    status_f = request.args.get("status")
    items = list(db.rsvps.values())
    if ev_f:
        items = [r for r in items if r["event_id"] == ev_f]
    if athlete_f:
        items = [r for r in items if r["athlete_id"] == athlete_f]
    if status_f:
        items = [r for r in items if r["status"] == status_f]
    items.sort(key=lambda r: r["created_at"])
    limit, offset, _ = parse_pagination(request.args)
    return ok_list([rsvp_view(r) for r in items], limit, offset)


@bp.get("/v1/rsvps/<rid>")
def get_rsvp(rid):
    require_roles("Athlete", "PlatformAdmin", "Moderator")
    r = db.rsvps.get(rid)
    if not r:
        raise err_not_found("RSVP not found")
    return ok_object(rsvp_view(r))


def _get_rsvp_scoped(eid, rid):
    ev = db.events.get(eid)
    if not ev:
        raise err_not_found("Event not found")
    r = db.rsvps.get(rid)
    if not r or r["event_id"] != eid:
        raise err_not_found("RSVP not found")
    return ev, r


@bp.post("/v1/events/<eid>/rsvps/<rid>/decline")
def decline_rsvp(eid, rid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    ev, r = _get_rsvp_scoped(eid, rid)
    check_self_or_admin(user_id, role, r["athlete_id"])
    if r["status"] != "GOING":
        raise err_invalid_state("Only GOING RSVPs may be declined")
    r["status"] = "DECLINED"
    touch(r)
    ev["rsvp_count"] = max(0, int(ev["rsvp_count"]) - 1)
    touch(ev)
    return ok_object(rsvp_view(r))


@bp.post("/v1/events/<eid>/rsvps/<rid>/rejoin")
def rejoin_rsvp(eid, rid):
    user_id, role = require_roles("Athlete", "PlatformAdmin")
    ev, r = _get_rsvp_scoped(eid, rid)
    lazy_complete_event(ev)
    check_self_or_admin(user_id, role, r["athlete_id"])
    if r["status"] != "DECLINED":
        raise err_invalid_state("Only DECLINED RSVPs may rejoin")
    if ev["status"] != "PUBLISHED":
        raise err_invalid_state("Event is not PUBLISHED")
    sched = parse_iso_dt(ev["scheduled_at"])
    if logical_now_dt() > sched:
        raise err_window("Cannot rejoin after scheduled_at")
    if int(ev["rsvp_count"]) >= int(ev["capacity"]):
        raise err_capacity()
    r["status"] = "GOING"
    touch(r)
    ev["rsvp_count"] = int(ev["rsvp_count"]) + 1
    touch(ev)
    return ok_object(rsvp_view(r))
