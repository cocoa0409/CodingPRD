"""GrillTable endpoints and the grill-table event endpoint."""
from flask import Blueprint

import constants as C
import db
import helpers as h
import services as svc
from errors import fail
from middleware import guard
from response import ok

bp = Blueprint("tables", __name__)

READ_ROLES = C.ROLES


@bp.route("/service-floor/tables", methods=["POST"])
def create_table():
    guard(["FloorManager"])
    body = h.payload()
    venue = svc.venue_or_404(h.as_string(body, "venue_id"))
    table = db.add("tables", db.new_row(
        venue_id=venue["id"],
        tier_code=h.as_string(body, "tier_code", enum=C.TIER_CODES),
        seat_capacity=h.as_int(body, "seat_capacity", minimum=1),
        status="AVAILABLE",
        maintenance_resume_at=None,
        pending_turn=False,
        guests_seated=0,
        last_seated_at=None,
    ))
    return ok(db.public(table), 201)


@bp.route("/service-floor/tables", methods=["GET"])
def list_tables():
    guard(READ_ROLES)
    rows = h.filter_rows(db.all_of("tables"), venue_id=h.q("venue_id"),
                         status=h.q("status"))
    data, page_meta = h.list_response(rows)
    return ok(data, 200, page_meta)


@bp.route("/service-floor/tables/<table_id>", methods=["GET"])
def get_table(table_id):
    guard(READ_ROLES)
    table = svc.table_or_404(table_id)
    return ok(db.public(table), 200)


@bp.route("/service-floor/tables/<table_id>/events", methods=["POST"])
def table_event(table_id):
    guard(["FloorManager"])
    table = svc.table_or_404(table_id)
    body = h.payload()
    event_type = h.as_string(body, "event_type")
    expected = h.as_int(body, "expected_table_version", required=False)
    if expected is not None and expected != table.get("version"):
        fail("ERR_STALE_VERSION")

    if event_type == "SEAT":
        return _seat(table, body)
    if event_type == "TURN":
        return _turn(table)
    if event_type == "TURN_RELEASE":
        return _turn_release(table)
    if event_type == "MAINTENANCE_ENTER":
        return _maintenance_enter(table, body)
    fail("ERR_INVALID_REQUEST", "Unknown table event_type: %s" % event_type)


def _seat(table, body):
    reservation = svc.reservation_or_404(h.as_string(body, "reservation_id"))
    if reservation.get("status") != "HELD":
        fail("ERR_INVALID_STATE")
    venue = db.get("venues", reservation["venue_id"])
    if venue.get("occupancy_freeze"):
        fail("ERR_VENTILATION_FREEZE")
    party = db.get("parties", reservation.get("party_id"))
    if party is not None and party.get("status") == "RESTRICTED":
        fail("ERR_PARTY_RESTRICTED")
    party_size = reservation.get("party_size", 0)
    if party_size > table.get("seat_capacity", 0) or \
            table.get("guests_seated", 0) + party_size > table.get("seat_capacity", 0):
        fail("ERR_TABLE_OVER_CAPACITY")
    chef = svc.select_chef_for(venue["id"], table.get("tier_code"))
    if chef is None:
        fail("ERR_CHEF_ROTATION_EXHAUSTED")
    reservation, _seating = svc.seat_reservation(reservation, table, chef)
    return ok(db.public(db.get("reservations", reservation["id"])), 200)


def _turn(table):
    if table.get("status") != "SEATED":
        fail("ERR_INVALID_STATE")
    return ok(db.public(svc.turn_table(table)), 200)


def _turn_release(table):
    if table.get("status") != "TURNING":
        fail("ERR_INVALID_STATE")
    return ok(db.public(svc.turn_release(table)), 200)


def _maintenance_enter(table, body):
    resume_at = h.as_datetime(body, "resume_at", required=False)
    if table.get("status") == "SEATED":
        if svc.active_seatings_at_table(table["id"]):
            fail("ERR_INVALID_STATE")
        for show in svc.shows_at_table(table["id"]):
            if show.get("status") in ("PLANNED", "STARTED"):
                db.touch(show, status="SKIPPED")
    elif table.get("status") == "TURNING":
        if table.get("guests_seated", 0) != 0:
            fail("ERR_INVALID_STATE")
    elif table.get("status") == "MAINTENANCE":
        pass
    else:
        fail("ERR_INVALID_STATE")
    return ok(db.public(svc.maintenance_enter(table, resume_at)), 200)