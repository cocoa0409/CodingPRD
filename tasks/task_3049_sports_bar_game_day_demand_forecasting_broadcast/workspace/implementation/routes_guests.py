"""Guests and waitlist."""
import math
from datetime import timedelta

from flask import Blueprint, request

import db
import errors
from util import success, list_response, auth, body, require, req_int, req_str, now_ts, bump
import services
from util import serialize, serialize_list

bp = Blueprint("guests", __name__)

READ_GUESTS = ["PlatformAdmin", "VenueManager", "Host", "Server"]
READ_WAITLIST = ["PlatformAdmin", "VenueManager", "Host"]


def get_guest_or_404(guest_id):
    g = db.guests.get(guest_id)
    if g is None:
        raise errors.guest_not_found()
    return g


def get_entry_or_404(entry_id):
    e = db.waitlist_entries.get(entry_id)
    if e is None:
        raise errors.not_found()
    return e


@bp.post("/api/guests")
def create_guest():
    auth(["Host", "Server"])
    data = body()
    venue_id = require(data, "venue_id")
    if venue_id not in db.venues:
        raise errors.not_found()
    name = req_str(data, "name")
    phone = req_str(data, "phone")
    ts = now_ts()
    guest = {
        "id": services.new_id(), "venue_id": venue_id, "name": name,
        "phone": phone, "no_show_count": 0,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db.guests[guest["id"]] = guest
    return success(serialize(guest), code=201)


@bp.get("/api/guests/<guest_id>")
def get_guest(guest_id):
    auth(READ_GUESTS)
    return success(serialize(get_guest_or_404(guest_id)))


@bp.get("/api/venues/<venue_id>/guests")
def list_venue_guests(venue_id):
    auth(READ_GUESTS)
    if venue_id not in db.venues:
        raise errors.not_found()
    items = sorted([g for g in db.guests.values() if g["venue_id"] == venue_id],
                   key=lambda g: g["created_at"])
    return list_response(serialize_list(items))


@bp.get("/api/guests/<guest_id>/waitlist-entries")
def guest_waitlist_entries(guest_id):
    auth(READ_WAITLIST)
    get_guest_or_404(guest_id)
    items = sorted([w for w in db.waitlist_entries.values()
                    if w["guest_id"] == guest_id],
                   key=lambda w: w["created_at"])
    return list_response(serialize_list(items))


@bp.get("/api/guests/<guest_id>/checks")
def guest_checks(guest_id):
    auth(["PlatformAdmin", "VenueManager", "Server"])
    get_guest_or_404(guest_id)
    items = sorted([c for c in db.checks.values() if c["guest_id"] == guest_id],
                   key=lambda c: c["created_at"])
    return list_response(serialize_list(items))


@bp.get("/api/guests/<guest_id>/trivia-entries")
def guest_trivia_entries(guest_id):
    auth(["PlatformAdmin", "VenueManager", "Host"])
    get_guest_or_404(guest_id)
    items = sorted([t for t in db.trivia_entries.values()
                    if t["guest_id"] == guest_id],
                   key=lambda t: t["created_at"])
    return list_response(serialize_list(items))


@bp.get("/api/guests/<guest_id>/fantasy-entries")
def guest_fantasy_entries(guest_id):
    auth(READ_GUESTS)
    get_guest_or_404(guest_id)
    items = sorted([f for f in db.fantasy_entries.values()
                    if f["guest_id"] == guest_id],
                   key=lambda f: f["created_at"])
    return list_response(serialize_list(items))


# ---------------------------------------------------------------- waitlist

@bp.post("/api/waitlist")
def join_waitlist():
    auth(["Host"])
    services.process_waitlist_timers()
    data = body()
    venue_id = require(data, "venue_id")
    venue = db.venues.get(venue_id)
    if venue is None:
        raise errors.not_found()
    guest_id = require(data, "guest_id")
    guest = get_guest_or_404(guest_id)
    party_size = require(data, "party_size")
    if isinstance(party_size, bool) or not isinstance(party_size, int):
        raise errors.invalid_request("party_size must be an integer")
    if party_size <= 0:
        raise errors.quantity_invalid("party_size must be a positive integer")
    kickoff_override = data.get("kickoff_override", False)
    if not isinstance(kickoff_override, bool):
        raise errors.invalid_request("kickoff_override must be a boolean")

    # Capacity gate: all zones FULL -> reject
    zones = [z for z in db.zones.values() if z["venue_id"] == venue_id]
    if zones and all(z["posture"] == "FULL" for z in zones):
        raise errors.waitlist_full()
    # No-show gate
    if guest["no_show_count"] >= 3:
        raise errors.too_many_no_shows()

    # Quote: 15 minutes per seating group ahead (WAITING entries at this venue)
    waiting = [w for w in db.waitlist_entries.values()
               if w["venue_id"] == venue_id and w["status"] == "WAITING"]
    groups = sum(math.ceil(w["party_size"] / 8) for w in waiting)
    quoted_wait_minutes = 15 * groups

    ts = now_ts()
    entry = {
        "id": services.new_id(), "venue_id": venue_id, "guest_id": guest_id,
        "party_size": party_size, "status": "WAITING", "called_at": None,
        "kickoff_override": kickoff_override,
        "quoted_wait_minutes": quoted_wait_minutes,
        "created_at": ts, "updated_at": ts, "version": 1,
    }
    db.waitlist_entries[entry["id"]] = entry
    return success(serialize(entry), code=201)


@bp.get("/api/venues/<venue_id>/waitlist-entries")
def list_venue_waitlist(venue_id):
    auth(READ_WAITLIST)
    if venue_id not in db.venues:
        raise errors.not_found()
    items = sorted([w for w in db.waitlist_entries.values()
                    if w["venue_id"] == venue_id],
                   key=lambda w: w["created_at"])
    status = request.args.get("status")
    if status is not None:
        items = [w for w in items if w["status"] == status]
    return list_response(serialize_list(items))


@bp.get("/api/waitlist-entries/<entry_id>")
def get_waitlist_entry(entry_id):
    auth(READ_WAITLIST)
    return success(serialize(get_entry_or_404(entry_id)))


@bp.post("/api/waitlist/<entry_id>/call")
def call_entry(entry_id):
    auth(["Host"])
    services.process_waitlist_timers()
    entry = get_entry_or_404(entry_id)
    if entry["status"] != "WAITING":
        raise errors.invalid_state("Entry is not WAITING")
    # Skip-guard: must be earliest-created WAITING entry at this venue
    waiting = sorted([w for w in db.waitlist_entries.values()
                      if w["venue_id"] == entry["venue_id"]
                      and w["status"] == "WAITING"],
                     key=lambda w: w["created_at"])
    if not waiting or waiting[0]["id"] != entry_id:
        raise errors.invalid_state("Entry is not the first WAITING entry")
    entry["status"] = "CALLED"
    entry["called_at"] = db.now()
    bump(entry)
    return success(serialize(entry))


@bp.post("/api/waitlist/<entry_id>/seat")
def seat_entry(entry_id):
    auth(["Host"])
    services.process_waitlist_timers()
    entry = get_entry_or_404(entry_id)
    if entry["status"] != "CALLED":
        raise errors.invalid_state("Entry is not CALLED")
    # Hold window check
    deadline = entry["called_at"] + timedelta(minutes=services.hold_minutes(entry))
    if db.now() > deadline:
        raise errors.table_hold_expired()
    # OCC
    data = body()
    expected = require(data, "expected_waitlist_entry_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise errors.invalid_request("expected_waitlist_entry_version must be an integer")
    if expected != entry["version"]:
        raise errors.stale_version()
    entry["status"] = "SEATED"
    bump(entry)
    guest = db.guests.get(entry["guest_id"])
    if guest is not None and guest["no_show_count"] > 0:
        guest["no_show_count"] -= 1
        bump(guest)
    return success(serialize(entry))


@bp.post("/api/waitlist/<entry_id>/cancel")
def cancel_entry(entry_id):
    auth(["Host"])
    services.process_waitlist_timers()
    entry = get_entry_or_404(entry_id)
    if entry["status"] not in ("WAITING", "CALLED"):
        raise errors.invalid_state("Entry cannot be cancelled from this state")
    entry["status"] = "CANCELLED"
    bump(entry)
    return success(serialize(entry))
