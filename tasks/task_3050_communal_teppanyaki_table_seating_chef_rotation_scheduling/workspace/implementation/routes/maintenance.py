"""MaintenanceWindow endpoints."""
from flask import Blueprint

import constants as C
import db
import helpers as h
import services as svc
from errors import fail
from middleware import guard
from response import ok

bp = Blueprint("maintenance", __name__)

READ_ROLES = C.ROLES


@bp.route("/service-floor/maintenance-windows", methods=["POST"])
def create_window():
    guard(["FloorManager"])
    body = h.payload()
    venue = svc.venue_or_404(h.as_string(body, "venue_id"))
    table_id = h.as_string(body, "table_id", required=False)
    if table_id is not None:
        table = svc.table_or_404(table_id)
        if table.get("venue_id") != venue["id"]:
            fail("ERR_TABLE_NOT_FOUND")
    start = h.as_datetime(body, "planned_start_at")
    end = h.as_datetime(body, "planned_end_at")
    svc.validate_booking_time(start)
    window = db.add("maintenance_windows", db.new_row(
        venue_id=venue["id"],
        table_id=table_id,
        maintenance_kind=h.as_string(body, "maintenance_kind", enum=C.WINDOW_KINDS),
        planned_start_at=start,
        planned_end_at=end,
        status="SCHEDULED",
    ))
    return ok(db.public(window), 201)


@bp.route("/service-floor/maintenance-windows", methods=["GET"])
def list_windows():
    guard(READ_ROLES)
    rows = h.filter_rows(db.all_of("maintenance_windows"), venue_id=h.q("venue_id"),
                         table_id=h.q("table_id"), status=h.q("status"))
    data, page_meta = h.list_response(rows)
    return ok(data, 200, page_meta)


@bp.route("/service-floor/maintenance-windows/<window_id>", methods=["GET"])
def get_window(window_id):
    guard(READ_ROLES)
    window = svc.window_or_404(window_id)
    return ok(db.public(window), 200)


@bp.route("/service-floor/maintenance-windows/<window_id>/accept", methods=["POST"])
def accept_window(window_id):
    guard(["FloorManager"])
    window = svc.window_or_404(window_id)
    if window.get("status") != "SCHEDULED":
        fail("ERR_INVALID_STATE")
    window = svc.accept_window(window)
    return ok(db.public(db.get("maintenance_windows", window["id"])), 200)


@bp.route("/service-floor/maintenance-windows/<window_id>/cancel", methods=["POST"])
def cancel_window(window_id):
    guard(["FloorManager"])
    window = svc.window_or_404(window_id)
    if window.get("status") != "SCHEDULED":
        fail("ERR_INVALID_STATE")
    window = svc.cancel_window(window)
    return ok(db.public(db.get("maintenance_windows", window["id"])), 200)


@bp.route("/service-floor/maintenance-windows/<window_id>/reopen", methods=["POST"])
def reopen_window(window_id):
    guard(["FloorManager"])
    window = svc.window_or_404(window_id)
    if window.get("status") != "ACTIVE":
        fail("ERR_INVALID_STATE")
    window = svc.reopen_window(window)
    return ok(db.public(db.get("maintenance_windows", window["id"])), 200)