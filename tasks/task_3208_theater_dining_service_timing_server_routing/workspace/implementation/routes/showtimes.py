"""Showtime routes and every lifecycle transition."""

from flask import Blueprint, request

import db
import middleware
import response as envelope
from services import core
from services import showtime as showtime_service

bp = Blueprint("showtimes", __name__)

ALL_ROLES = ["PlatformAdmin", "KitchenLead", "ProgrammingCoordinator", "PreShowProducer",
             "Server"]
CREW_ROLES = ["PlatformAdmin", "KitchenLead", "Server"]


def _capacity_body(st):
    return core.capacity_snapshot(st)


@bp.route("/showtimes", methods=["POST"])
def create_showtime():
    middleware.principal_for(["PlatformAdmin", "ProgrammingCoordinator"])
    data = middleware.body()
    row = showtime_service.create(data)
    return envelope.ok(envelope.s_showtime(row), "object", 201)


@bp.route("/showtimes", methods=["GET"])
def list_showtimes():
    middleware.principal_for(ALL_ROLES)
    aud_id = request.args.get("auditorium_id")
    status = request.args.get("status")
    rows = []
    for st in db.db.sorted_rows("showtimes"):
        if aud_id is not None and st["auditorium_id"] != aud_id:
            continue
        if status is not None and st["status"] != status:
            continue
        rows.append(st)
    limit, offset = middleware.pagination()
    return envelope.ok_list(rows, limit, offset, len(rows), envelope.s_showtime)


@bp.route("/showtimes/<st_id>", methods=["GET"])
def get_showtime(st_id):
    middleware.principal_for(ALL_ROLES)
    st = core.showtime(st_id)
    core.recompute_service_mode(st)
    return envelope.ok(envelope.s_showtime(st), "object")


@bp.route("/showtimes/<st_id>/dining-capacity", methods=["GET"])
def dining_capacity(st_id):
    middleware.principal_for(CREW_ROLES)
    st = core.showtime(st_id)
    core.recompute_service_mode(st)
    return envelope.ok(_capacity_body(st), "object")


@bp.route("/showtimes/<st_id>/section-assignments", methods=["GET"])
def list_sections(st_id):
    middleware.principal_for(ALL_ROLES)
    core.showtime(st_id)
    status = request.args.get("status")
    rows = [a for a in db.db.sorted_rows("section_assignments")
            if a["showtime_id"] == st_id and (status is None or a["status"] == status)]
    limit, offset = middleware.pagination()
    return envelope.ok_list(rows, limit, offset, len(rows), envelope.s_section_assignment)


@bp.route("/showtimes/<st_id>/kitchen-tickets", methods=["GET"])
def list_tickets(st_id):
    middleware.principal_for(CREW_ROLES)
    core.showtime(st_id)
    station = request.args.get("station")
    status = request.args.get("status")
    rows = [t for t in db.db.sorted_rows("kitchen_tickets")
            if t["showtime_id"] == st_id
            and (station is None or t["station"] == station)
            and (status is None or t["status"] == status)]
    rows.sort(key=lambda t: (t["sequence_position"] == 0, t["sequence_position"],
                             db.db.order.get(t["id"], 0)))
    limit, offset = middleware.pagination()
    return envelope.ok_list(rows, limit, offset, len(rows), envelope.s_kitchen_ticket)


@bp.route("/showtimes/<st_id>/order-slips", methods=["GET"])
def list_slips(st_id):
    middleware.principal_for(ALL_ROLES)
    core.showtime(st_id)
    status = request.args.get("status")
    rows = [s for s in db.db.sorted_rows("order_slips")
            if s["showtime_id"] == st_id and (status is None or s["status"] == status)]
    limit, offset = middleware.pagination()
    return envelope.ok_list(rows, limit, offset, len(rows), envelope.s_order_slip)


@bp.route("/showtimes/<st_id>/open-dining", methods=["POST"])
def open_dining(st_id):
    middleware.principal_for(["KitchenLead"])
    st = core.showtime(st_id)
    showtime_service.open_dining(st)
    return envelope.ok(envelope.s_showtime(st), "object")


@bp.route("/showtimes/<st_id>/start-service", methods=["POST"])
def start_service(st_id):
    middleware.principal_for(["KitchenLead"])
    st = core.showtime(st_id)
    showtime_service.start_service(st)
    return envelope.ok(envelope.s_showtime(st), "object")


@bp.route("/showtimes/<st_id>/start-feature", methods=["POST"])
def start_feature(st_id):
    middleware.principal_for(["KitchenLead", "PlatformAdmin"])
    st = core.showtime(st_id)
    showtime_service.start_feature(st)
    return envelope.ok(envelope.s_showtime(st), "object")


@bp.route("/showtimes/<st_id>/complete", methods=["POST"])
def complete(st_id):
    middleware.principal_for(["KitchenLead"])
    st = core.showtime(st_id)
    showtime_service.complete(st)
    return envelope.ok(envelope.s_showtime(st), "object")


@bp.route("/showtimes/<st_id>/reopen-service", methods=["POST"])
def reopen_service(st_id):
    middleware.principal_for(["KitchenLead"])
    st = core.showtime(st_id)
    showtime_service.reopen_service(st)
    return envelope.ok(envelope.s_showtime(st), "object")


@bp.route("/showtimes/<st_id>/cancel", methods=["POST"])
def cancel(st_id):
    middleware.principal_for(["ProgrammingCoordinator"])
    st = core.showtime(st_id)
    showtime_service.cancel(st)
    return envelope.ok(envelope.s_showtime(st), "object")