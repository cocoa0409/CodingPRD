"""ChefAssignment endpoints."""
from flask import Blueprint

import constants as C
import db
import helpers as h
import services as svc
from errors import fail
from middleware import guard
from response import ok

bp = Blueprint("chefs", __name__)

READ_ROLES = C.ROLES


@bp.route("/service-floor/chefs", methods=["POST"])
def create_chef():
    guard(["FloorManager"])
    body = h.payload()
    venue = svc.venue_or_404(h.as_string(body, "venue_id"))
    chef = db.add("chefs", db.new_row(
        venue_id=venue["id"],
        chef_name=h.as_string(body, "chef_name"),
        station_zone=h.as_string(body, "station_zone", enum=C.ZONES),
        status="OFF_SHIFT",
        sequence_index=None,
        current_table_id=None,
        completed_show_count=0,
        pounds_protein_issued=0,
        minutes_since_show=0,
    ))
    return ok(db.public(chef), 201)


@bp.route("/service-floor/chefs", methods=["GET"])
def list_chefs():
    guard(READ_ROLES)
    rows = h.filter_rows(db.all_of("chefs"), venue_id=h.q("venue_id"),
                         current_table_id=h.q("current_table_id"), status=h.q("status"))
    data, page_meta = h.list_response(rows)
    return ok(data, 200, page_meta)


@bp.route("/service-floor/chefs/<chef_id>", methods=["GET"])
def get_chef(chef_id):
    guard(READ_ROLES)
    chef = svc.chef_or_404(chef_id)
    chef = db.touch(chef, minutes_since_show=svc.minutes_since_show(chef))
    return ok(db.public(chef), 200)


@bp.route("/service-floor/chefs/<chef_id>/events", methods=["POST"])
def chef_event(chef_id):
    chef = svc.chef_or_404(chef_id)
    body = h.payload()
    event_type = h.as_string(body, "event_type")
    guard(["Chef", "FloorManager"], owner_getter=lambda: chef.get("id"))

    venue = db.get("venues", chef["venue_id"])
    expected = h.as_int(body, "expected_venue_version", required=False)
    if expected is not None and venue is not None and expected != venue.get("version"):
        fail("ERR_STALE_VERSION")

    chef = svc.chef_event(chef, event_type)
    if venue is not None:
        db.touch(venue)
    return ok(db.public(db.get("chefs", chef["id"])), 200)