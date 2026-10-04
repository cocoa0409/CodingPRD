"""TableSeating endpoints."""
from datetime import timedelta

from flask import Blueprint

import constants as C
import db
import helpers as h
import services as svc
from errors import fail
from middleware import guard
from response import ok

bp = Blueprint("seatings", __name__)

READ_ROLES = C.ROLES


@bp.route("/service-floor/seatings", methods=["GET"])
def list_seatings():
    guard(READ_ROLES)
    rows = h.filter_rows(db.all_of("seatings"), venue_id=h.q("venue_id"),
                         table_id=h.q("table_id"), reservation_id=h.q("reservation_id"),
                         status=h.q("status"))
    data, page_meta = h.list_response(rows)
    return ok(data, 200, page_meta)


@bp.route("/service-floor/seatings/<seating_id>", methods=["GET"])
def get_seating(seating_id):
    guard(READ_ROLES)
    seating = svc.seating_or_404(seating_id)
    seating = db.touch(seating, occupied_minutes=svc.occupied_minutes(seating))
    return ok(db.public(seating), 200)


@bp.route("/service-floor/seatings/<seating_id>/extend", methods=["POST"])
def extend_seating(seating_id):
    guard(["FloorManager"])
    seating = svc.seating_or_404(seating_id)
    body = h.payload()
    extension = h.as_int(body, "extension_minutes", minimum=1)
    if seating.get("status") != "ACTIVE":
        fail("ERR_INVALID_STATE")

    current_start = seating.get("seated_at")
    current_end = seating.get("expected_vacate_at")
    new_end = current_end + timedelta(minutes=extension)

    if svc.table_maintenance_conflict(seating["table_id"], current_start, new_end):
        fail("ERR_MAINTENANCE_CONFLICT")
    if svc.existing_reservation_hold_conflict(seating["table_id"], current_start, new_end,
                                              seating.get("reservation_id")):
        fail("ERR_MAINTENANCE_CONFLICT")

    seating = db.touch(seating, expected_vacate_at=new_end)
    return ok(db.public(db.get("seatings", seating["id"])), 200)