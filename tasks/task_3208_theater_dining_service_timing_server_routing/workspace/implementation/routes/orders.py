"""Order slips, kitchen tickets, checks, and disturbance events."""

from flask import Blueprint, request

import db
import middleware
import response as envelope
from services import core
from services import disturbance as disturbance_service
from services import kitchen as kitchen_service
from services import order as order_service

bp = Blueprint("orders", __name__)

ALL_ROLES = ["PlatformAdmin", "KitchenLead", "ProgrammingCoordinator", "PreShowProducer",
             "Server"]
CREW_ROLES = ["PlatformAdmin", "KitchenLead", "Server"]


# --- OrderSlip --------------------------------------------------------------

@bp.route("/order-slips", methods=["POST"])
def place_slip():
    principal = middleware.principal_for(["Server"])
    data = middleware.body()
    row = order_service.place(principal, data)
    return envelope.ok(envelope.s_order_slip(row), "object", 201)


@bp.route("/order-slips", methods=["GET"])
def list_slips():
    middleware.principal_for(ALL_ROLES)
    showtime_id = request.args.get("showtime_id")
    assignment_id = request.args.get("section_assignment_id")
    status = request.args.get("status")
    rows = []
    for s in db.db.sorted_rows("order_slips"):
        if showtime_id is not None and s["showtime_id"] != showtime_id:
            continue
        if assignment_id is not None and s["section_assignment_id"] != assignment_id:
            continue
        if status is not None and s["status"] != status:
            continue
        rows.append(s)
    limit, offset = middleware.pagination()
    return envelope.ok_list(rows, limit, offset, len(rows), envelope.s_order_slip)


@bp.route("/order-slips/<slip_id>", methods=["GET"])
def get_slip(slip_id):
    middleware.principal_for(ALL_ROLES)
    slip = core.order_slip(slip_id)
    return envelope.ok(envelope.s_order_slip(slip), "object")


@bp.route("/order-slips/<slip_id>/prepare", methods=["POST"])
def prepare(slip_id):
    principal = middleware.principal_for(["Server"])
    slip = core.order_slip(slip_id)
    order_service.prepare(principal, slip)
    return envelope.ok(envelope.s_order_slip(slip), "object")


@bp.route("/order-slips/<slip_id>/mark-ready", methods=["POST"])
def mark_ready(slip_id):
    principal = middleware.principal_for(["Server"])
    slip = core.order_slip(slip_id)
    order_service.mark_ready(principal, slip)
    return envelope.ok(envelope.s_order_slip(slip), "object")


@bp.route("/order-slips/<slip_id>/deliver", methods=["POST"])
def deliver(slip_id):
    principal = middleware.principal_for(["Server"])
    slip = core.order_slip(slip_id)
    order_service.deliver(principal, slip)
    return envelope.ok(envelope.s_order_slip(slip), "object")


@bp.route("/order-slips/<slip_id>/cancel", methods=["POST"])
def cancel_slip(slip_id):
    middleware.principal_for(["KitchenLead"])
    slip = core.order_slip(slip_id)
    data = middleware.body()
    order_service.cancel(slip, data)
    return envelope.ok(envelope.s_order_slip(slip), "object")


# --- KitchenTicket ----------------------------------------------------------

@bp.route("/kitchen-tickets", methods=["GET"])
def list_tickets():
    middleware.principal_for(CREW_ROLES)
    showtime_id = request.args.get("showtime_id")
    slip_id = request.args.get("order_slip_id")
    station = request.args.get("station")
    status = request.args.get("status")
    rows = []
    for t in db.db.sorted_rows("kitchen_tickets"):
        if showtime_id is not None and t["showtime_id"] != showtime_id:
            continue
        if slip_id is not None and t["order_slip_id"] != slip_id:
            continue
        if station is not None and t["station"] != station:
            continue
        if status is not None and t["status"] != status:
            continue
        rows.append(t)
    rows.sort(key=lambda t: (t["sequence_position"] == 0, t["sequence_position"],
                             db.db.order.get(t["id"], 0)))
    limit, offset = middleware.pagination()
    return envelope.ok_list(rows, limit, offset, len(rows), envelope.s_kitchen_ticket)


@bp.route("/kitchen-tickets/<ticket_id>", methods=["GET"])
def get_ticket(ticket_id):
    middleware.principal_for(CREW_ROLES)
    ticket = core.kitchen_ticket(ticket_id)
    return envelope.ok(envelope.s_kitchen_ticket(ticket), "object")


@bp.route("/kitchen-tickets/<ticket_id>/ack-overflow", methods=["POST"])
def ack_overflow(ticket_id):
    middleware.principal_for(["KitchenLead"])
    ticket = core.kitchen_ticket(ticket_id)
    data = middleware.body()
    kitchen_service.ack_overflow(ticket, data)
    return envelope.ok(envelope.s_kitchen_ticket(ticket), "object")


@bp.route("/kitchen-tickets/<ticket_id>/verify-id", methods=["POST"])
def verify_id(ticket_id):
    middleware.principal_for(["Server"])
    ticket = core.kitchen_ticket(ticket_id)
    data = middleware.body()
    kitchen_service.verify_id(ticket, data)
    return envelope.ok(envelope.s_kitchen_ticket(ticket), "object")


@bp.route("/kitchen-tickets/<ticket_id>/refresh", methods=["POST"])
def refresh_ticket(ticket_id):
    middleware.principal_for(["KitchenLead"])
    ticket = core.kitchen_ticket(ticket_id)
    kitchen_service.refresh(ticket)
    return envelope.ok(envelope.s_kitchen_ticket(ticket), "object")


@bp.route("/kitchen-tickets/<ticket_id>/void", methods=["POST"])
def void_ticket(ticket_id):
    middleware.principal_for(["KitchenLead"])
    ticket = core.kitchen_ticket(ticket_id)
    data = middleware.body()
    kitchen_service.void(ticket, data)
    return envelope.ok(envelope.s_kitchen_ticket(ticket), "object")


# --- CheckTab ---------------------------------------------------------------

@bp.route("/checks", methods=["GET"])
def list_checks():
    middleware.principal_for(CREW_ROLES)
    slip_id = request.args.get("order_slip_id")
    check_id = request.args.get("id")
    status = request.args.get("status")
    rows = []
    for tab in db.db.sorted_rows("checks"):
        if slip_id is not None and tab["order_slip_id"] != slip_id:
            continue
        if check_id is not None and tab["id"] != check_id:
            continue
        if status is not None and tab["status"] != status:
            continue
        rows.append(tab)
    limit, offset = middleware.pagination()
    return envelope.ok_list(rows, limit, offset, len(rows), envelope.s_check)


@bp.route("/checks/<check_id>", methods=["GET"])
def get_check(check_id):
    middleware.principal_for(CREW_ROLES)
    tab = core.check(check_id)
    return envelope.ok(envelope.s_check(tab), "object")


@bp.route("/checks/<check_id>/close", methods=["POST"])
def close_check(check_id):
    middleware.principal_for(["Server", "KitchenLead"])
    data = middleware.body()
    tab = core.check(check_id)
    order_service.close_check(tab, data)
    return envelope.ok(envelope.s_check(tab), "object")


@bp.route("/checks/<check_id>/refund", methods=["POST"])
def refund(check_id):
    middleware.principal_for(["KitchenLead"])
    data = middleware.body()
    tab = core.check(check_id)
    order_service.refund(tab, data)
    return envelope.ok(envelope.s_check(tab), "object")


# --- DisturbanceEvent -------------------------------------------------------

@bp.route("/disturbance-events", methods=["POST"])
def create_disturbance():
    principal = middleware.principal_for(["Server"])
    data = middleware.body()
    row = disturbance_service.create(principal, data)
    return envelope.ok(envelope.s_disturbance(row), "object", 201)


@bp.route("/disturbance-events", methods=["GET"])
def list_disturbances():
    middleware.principal_for(CREW_ROLES)
    disturbance_service.expire_stages()
    slip_id = request.args.get("order_slip_id")
    kind = request.args.get("kind")
    rows = []
    for ev in db.db.sorted_rows("disturbance_events"):
        if slip_id is not None and ev["order_slip_id"] != slip_id:
            continue
        if kind is not None and ev["kind"] != kind:
            continue
        rows.append(ev)
    limit, offset = middleware.pagination()
    return envelope.ok_list(rows, limit, offset, len(rows), envelope.s_disturbance)


@bp.route("/disturbance-events/<event_id>", methods=["GET"])
def get_disturbance(event_id):
    middleware.principal_for(CREW_ROLES)
    ev = core.disturbance(event_id)
    disturbance_service.expire_stages()
    return envelope.ok(envelope.s_disturbance(ev), "object")


@bp.route("/disturbance-events/<event_id>/amend", methods=["POST"])
def amend_disturbance(event_id):
    principal = middleware.principal_for(["Server", "KitchenLead"])
    ev = core.disturbance(event_id)
    data = middleware.body()
    disturbance_service.amend(principal, ev, data)
    return envelope.ok(envelope.s_disturbance(ev), "object")


@bp.route("/disturbance-events/<event_id>/approve-ejection", methods=["POST"])
def approve_ejection(event_id):
    middleware.principal_for(["KitchenLead"])
    ev = core.disturbance(event_id)
    disturbance_service.approve_ejection(ev)
    return envelope.ok(envelope.s_disturbance(ev), "object")