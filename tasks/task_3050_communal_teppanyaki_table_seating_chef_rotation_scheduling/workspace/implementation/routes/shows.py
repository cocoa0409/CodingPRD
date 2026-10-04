"""ShowPerformance endpoints."""
from flask import Blueprint

import constants as C
import db
import helpers as h
import services as svc
from errors import fail
from middleware import guard
from response import ok

bp = Blueprint("shows", __name__)

READ_ROLES = C.ROLES


@bp.route("/service-floor/shows", methods=["GET"])
def list_shows():
    guard(READ_ROLES)
    rows = h.filter_rows(
        db.all_of("shows"),
        venue_id=h.q("venue_id"), reservation_id=h.q("reservation_id"),
        chef_assignment_id=h.q("chef_assignment_id"), table_id=h.q("table_id"),
        protein_ticket_id=h.q("protein_ticket_id"), course_phase=h.q("course_phase"),
        status=h.q("status"))
    data, page_meta = h.list_response(rows)
    return ok(data, 200, page_meta)


@bp.route("/service-floor/shows/<show_id>", methods=["GET"])
def get_show(show_id):
    guard(READ_ROLES)
    show = svc.show_or_404(show_id)
    return ok(db.public(show), 200)


@bp.route("/service-floor/shows/<show_id>/events", methods=["POST"])
def show_event(show_id):
    show = svc.show_or_404(show_id)
    body = h.payload()
    event_type = h.as_string(body, "event_type")
    guard(["Chef", "FloorManager"], owner_getter=lambda: show.get("chef_assignment_id"))

    if event_type == "START":
        show = svc.start_show(show)
    elif event_type == "FINISH":
        show = svc.finish_show(show)
    elif event_type == "SKIP":
        show = svc.skip_show(show)
    elif event_type == "REINSTATE":
        show = svc.reinstate_show(show)
    else:
        fail("ERR_INVALID_REQUEST", "Unknown show event_type: %s" % event_type)
    return ok(_show_event_data(show), 200)


def _show_event_data(show):
    """Project a show row for a show-event response.

    A GRILL phase carries the booking's money slots: §3.5 has the GRILL FINISH
    recompute the settlement, so the settled `final_bill_cents` / `check_cents` ride
    along with the phase, and the provisional `quote_final_cents` is reported too.
    """
    data = db.public(show)
    if show.get("course_phase") == "GRILL":
        reservation = db.get("reservations", show.get("reservation_id"))
        if reservation is not None:
            data["final_bill_cents"] = reservation.get("final_bill_cents", 0)
            data["quote_final_cents"] = reservation.get("quote_final_cents", 0)
            data["check_cents"] = reservation.get("check_cents", 0)
    return data