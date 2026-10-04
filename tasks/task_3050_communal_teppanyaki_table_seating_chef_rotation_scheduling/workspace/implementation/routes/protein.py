"""ProteinTicket endpoints."""
from flask import Blueprint

import constants as C
import db
import helpers as h
import services as svc
from errors import fail
from middleware import guard
from response import ok

bp = Blueprint("protein", __name__)

READ_ROLES = C.ROLES


@bp.route("/service-floor/protein-tickets", methods=["GET"])
def list_tickets():
    guard(READ_ROLES)
    rows = h.filter_rows(db.all_of("protein_tickets"), venue_id=h.q("venue_id"),
                         reservation_id=h.q("reservation_id"),
                         chef_assignment_id=h.q("chef_assignment_id"),
                         show_id=h.q("show_id"), status=h.q("status"))
    data, page_meta = h.list_response(rows)
    return ok(data, 200, page_meta)


@bp.route("/service-floor/protein-tickets/<ticket_id>", methods=["GET"])
def get_ticket(ticket_id):
    guard(READ_ROLES)
    ticket = svc.protein_or_404(ticket_id)
    return ok(db.public(ticket), 200)


@bp.route("/service-floor/protein-tickets/<ticket_id>/variance", methods=["POST"])
def variance(ticket_id):
    ticket = svc.protein_or_404(ticket_id)
    body = h.payload()
    guard(["Chef", "FloorManager"],
          owner_getter=lambda: ticket.get("chef_assignment_id"))
    delta = h.as_int(body, "delta_grams")
    ticket = svc.protein_variance(ticket, delta)
    return ok(db.public(db.get("protein_tickets", ticket["id"])), 200)


@bp.route("/service-floor/protein-tickets/<ticket_id>/events", methods=["POST"])
def protein_event(ticket_id):
    ticket = svc.protein_or_404(ticket_id)
    body = h.payload()
    event_type = h.as_string(body, "event_type")
    guard(["Chef"], owner_getter=lambda: ticket.get("chef_assignment_id"))
    if event_type != "VOID":
        fail("ERR_INVALID_REQUEST", "Unknown protein event_type: %s" % event_type)
    if ticket.get("status") != "POSTED":
        fail("ERR_INVALID_STATE")
    ticket = svc.protein_void(ticket)
    return ok(db.public(db.get("protein_tickets", ticket["id"])), 200)