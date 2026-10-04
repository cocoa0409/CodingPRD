"""SushiTicket endpoints."""
from flask import Blueprint

import constants as C
import db
import helpers as h
import services as svc
from errors import fail
from middleware import guard
from response import ok

bp = Blueprint("sushi", __name__)

READ_ROLES = C.ROLES


@bp.route("/service-floor/sushi-tickets", methods=["POST"])
def create_ticket():
    guard(["SushiChef"])
    body = h.payload()
    venue = svc.venue_or_404(h.as_string(body, "venue_id"))
    reservation = svc.reservation_or_404(h.as_string(body, "reservation_id"))
    ticket = db.add("sushi_tickets", db.new_row(
        venue_id=venue["id"],
        reservation_id=reservation["id"],
        item_code=h.as_string(body, "item_code"),
        quantity=h.as_int(body, "quantity", minimum=1),
        requested_at=h.as_datetime(body, "requested_at"),
        unit_price_cents=h.as_int(body, "unit_price_cents", minimum=0),
        prep_phase="RAW_CUT",
        status="OPEN",
    ))
    return ok(db.public(ticket), 201)


@bp.route("/service-floor/sushi-tickets", methods=["GET"])
def list_tickets():
    guard(READ_ROLES)
    rows = h.filter_rows(db.all_of("sushi_tickets"), venue_id=h.q("venue_id"),
                         reservation_id=h.q("reservation_id"),
                         prep_phase=h.q("prep_phase"), status=h.q("status"))
    data, page_meta = h.list_response(rows)
    return ok(data, 200, page_meta)


@bp.route("/service-floor/sushi-tickets/<ticket_id>", methods=["GET"])
def get_ticket(ticket_id):
    guard(READ_ROLES)
    ticket = svc.sushi_ticket_or_404(ticket_id)
    return ok(db.public(ticket), 200)


@bp.route("/service-floor/sushi-tickets/<ticket_id>/events", methods=["POST"])
def sushi_event(ticket_id):
    ticket = svc.sushi_ticket_or_404(ticket_id)
    body = h.payload()
    event_type = h.as_string(body, "event_type")
    reservation = db.get("reservations", ticket.get("reservation_id"))
    owner = reservation.get("chef_assignment_id") if reservation else None
    guard(["SushiChef"], owner_getter=lambda: owner)

    ticket = svc.sushi_event(ticket, event_type)
    return ok(db.public(db.get("sushi_tickets", ticket["id"])), 200)