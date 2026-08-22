"""Shows: the deadline calendar and the show lifecycle cascades (PRD §3.1)."""
from flask import Blueprint

import db
import guards
import response
from errors import ApiError
from middleware import ANY_ROLE, require_roles
from services import state
from validation import json_body, parse_dt, require_row

bp = Blueprint("shows", __name__)
store = db.store

SHOW_STATUSES = ("DRAFT", "OPEN_FOR_ORDERS", "ADVANCE_CLOSED", "MOVE_IN", "ON_SITE",
                 "MOVE_OUT", "CLOSED", "CANCELLED")
TERMINAL = ("CLOSED", "CANCELLED")
EDGES = {
    "OPEN_FOR_ORDERS": ("DRAFT",),
    "ADVANCE_CLOSED": ("OPEN_FOR_ORDERS",),
    "MOVE_IN": ("ADVANCE_CLOSED",),
    "ON_SITE": ("MOVE_IN",),
    "MOVE_OUT": ("ON_SITE",),
    "CLOSED": ("MOVE_OUT",),
    "CANCELLED": ("DRAFT", "OPEN_FOR_ORDERS", "ADVANCE_CLOSED"),
}
CALENDAR_FIELDS = ("discount_deadline", "advance_warehouse_deadline", "move_in_start",
                   "move_in_end", "show_open", "show_close", "move_out_end")


@bp.post("/shows")
def create_show():
    require_roles("ShowOperations")
    body = json_body()
    venue_id = body.string("venue_id")
    name = body.string("name")
    calendar = {field: body.datetime_str(field) for field in CALENDAR_FIELDS}

    require_row(store.venues, venue_id, "ERR_VENUE_NOT_FOUND", "Venue")

    show = {"id": db.new_id(), "venue_id": venue_id, "name": name}
    for field in CALENDAR_FIELDS:
        show[field] = calendar[field]
    show["status"] = "DRAFT"
    show["committed_labor_hours"] = 0
    show["cancelled_labor_call_count"] = 0
    db.stamp_common(show)
    store.shows[show["id"]] = show
    return response.created(show)


@bp.get("/shows/<show_id>")
def get_show(show_id):
    require_roles(ANY_ROLE)
    show = require_row(store.shows, show_id, "ERR_SHOW_NOT_FOUND", "Show")
    return response.ok(show)


@bp.get("/shows")
def list_shows():
    require_roles(ANY_ROLE)
    rows = list(store.shows.values())
    rows = response.filter_rows(rows, "venue_id", "status")
    return response.listing(rows)


@bp.post("/shows/<show_id>/status")
def advance_show(show_id):
    require_roles("ShowOperations")
    body = json_body()
    to_status = body.enum("to_status", SHOW_STATUSES)
    show = require_row(store.shows, show_id, "ERR_SHOW_NOT_FOUND", "Show")

    guards.transition(show["status"], TERMINAL, EDGES.get(to_status, ()))

    if to_status == "OPEN_FOR_ORDERS":
        _validate_calendar(show)
    if to_status == "CLOSED":
        for call in state.calls_of_show(show_id):
            if call["status"] in ("DISPATCHED", "ON_SITE"):
                raise ApiError("ERR_INVALID_STATE_TRANSITION",
                               "Crews must be off the floor before the show can close")

    show["status"] = to_status
    db.touch(show)

    if to_status == "MOVE_OUT":
        _cascade_move_out(show)
    elif to_status == "CLOSED":
        state.refresh_show_booths(show_id)
        for license_row in state.licenses_of_show(show_id):
            if license_row["status"] == "PROVISIONED":
                license_row["status"] = "CLOSED"
                db.touch(license_row)
    elif to_status == "CANCELLED":
        _cascade_cancel(show)

    return response.ok(show)


def _validate_calendar(show):
    values = {field: parse_dt(show[field]) for field in CALENDAR_FIELDS}
    ok = (values["discount_deadline"] < values["advance_warehouse_deadline"]
          < values["move_in_start"] < values["move_in_end"]
          and values["move_in_end"] <= values["show_open"] < values["show_close"]
          and values["show_close"] <= values["move_out_end"])
    if not ok:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "The show calendar does not satisfy the required ordering")


def _cascade_move_out(show):
    """Delivered shipments close and their freight holds lift; ACTIVE licences close."""
    for shipment in list(store.shipments.values()):
        if shipment["show_id"] != show["id"] or shipment["status"] != "DELIVERED_TO_BOOTH":
            continue
        shipment["status"] = "CLOSED"
        shipment["hold_flag"] = False
        db.touch(shipment)
        state.refresh_exhibitor_show_booths(shipment["exhibitor_id"], show["id"])
    for license_row in state.licenses_of_show(show["id"]):
        if license_row["status"] == "ACTIVE":
            license_row["status"] = "CLOSED"
            db.touch(license_row)


def _cascade_cancel(show):
    """Live service orders are cancelled, then every booth freezes."""
    booth_ids = {b["id"] for b in state.booths_of_show(show["id"])}
    for order in list(store.service_orders.values()):
        if order["booth_id"] in booth_ids and order["fulfillment_status"] in (
                "PENDING", "CONFIRMED", "SCHEDULED", "HELD"):
            order["fulfillment_status"] = "CANCELLED"
            db.touch(order)
    state.refresh_show_booths(show["id"])
