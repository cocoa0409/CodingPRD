"""Server profiles, shifts, ratings, penalties, and section rostering."""

from flask import Blueprint, request

import db
import middleware
import response as envelope
from services import core
from services import section as section_service

bp = Blueprint("servers", __name__)

ALL_ROLES = ["PlatformAdmin", "KitchenLead", "ProgrammingCoordinator", "PreShowProducer",
             "Server"]


@bp.route("/servers", methods=["POST"])
def create_server():
    middleware.principal_for(["PlatformAdmin", "KitchenLead"])
    data = middleware.body()
    row = section_service.create_server(data)
    return envelope.ok(envelope.s_server(row), "object", 201)


@bp.route("/servers", methods=["GET"])
def list_servers():
    middleware.principal_for(ALL_ROLES)
    aud_id = request.args.get("home_auditorium_id")
    status = request.args.get("status")
    rows = []
    for srv in db.db.sorted_rows("servers"):
        if aud_id is not None and srv["home_auditorium_id"] != aud_id:
            continue
        if status is not None and srv["status"] != status:
            continue
        rows.append(srv)
    limit, offset = middleware.pagination()
    return envelope.ok_list(rows, limit, offset, len(rows), envelope.s_server)


@bp.route("/servers/<srv_id>", methods=["GET"])
def get_server(srv_id):
    middleware.principal_for(ALL_ROLES)
    srv = core.server(srv_id)
    core.refresh_server(srv)
    return envelope.ok(envelope.s_server(srv), "object")


@bp.route("/servers/<srv_id>/shift/start", methods=["POST"])
def shift_start(srv_id):
    middleware.principal_for(["KitchenLead"])
    srv = core.server(srv_id)
    section_service.shift_start(srv)
    return envelope.ok(envelope.s_server(srv), "object")


@bp.route("/servers/<srv_id>/shift/end", methods=["POST"])
def shift_end(srv_id):
    middleware.principal_for(["KitchenLead"])
    srv = core.server(srv_id)
    section_service.shift_end(srv)
    return envelope.ok(envelope.s_server(srv), "object")


@bp.route("/servers/<srv_id>/rate", methods=["POST"])
def rate_server(srv_id):
    middleware.principal_for(["KitchenLead"])
    srv = core.server(srv_id)
    data = middleware.body()
    section_service.rate(srv, data)
    return envelope.ok(envelope.s_server(srv), "object")


@bp.route("/servers/<srv_id>/clear-penalty", methods=["POST"])
def clear_penalty(srv_id):
    middleware.principal_for(["PlatformAdmin", "KitchenLead"])
    srv = core.server(srv_id)
    section_service.clear_penalty(srv)
    return envelope.ok(envelope.s_server(srv), "object")


@bp.route("/servers/<srv_id>/section-assignments", methods=["GET"])
def list_server_sections(srv_id):
    middleware.principal_for(ALL_ROLES)
    core.server(srv_id)
    status = request.args.get("status")
    rows = [a for a in db.db.sorted_rows("section_assignments")
            if a["server_id"] == srv_id and (status is None or a["status"] == status)]
    limit, offset = middleware.pagination()
    return envelope.ok_list(rows, limit, offset, len(rows), envelope.s_section_assignment)


# --- SectionAssignment ------------------------------------------------------

@bp.route("/section-assignments", methods=["POST"])
def create_assignment():
    middleware.principal_for(["KitchenLead"])
    data = middleware.body()
    row = section_service.create_assignment(data)
    return envelope.ok(envelope.s_section_assignment(row), "object", 201)


@bp.route("/section-assignments", methods=["GET"])
def list_assignments():
    middleware.principal_for(ALL_ROLES)
    showtime_id = request.args.get("showtime_id")
    server_id = request.args.get("server_id")
    aud_id = request.args.get("auditorium_id")
    status = request.args.get("status")
    rows = []
    for a in db.db.sorted_rows("section_assignments"):
        if showtime_id is not None and a["showtime_id"] != showtime_id:
            continue
        if server_id is not None and a["server_id"] != server_id:
            continue
        if aud_id is not None and a["auditorium_id"] != aud_id:
            continue
        if status is not None and a["status"] != status:
            continue
        rows.append(a)
    limit, offset = middleware.pagination()
    return envelope.ok_list(rows, limit, offset, len(rows), envelope.s_section_assignment)


@bp.route("/section-assignments/<assignment_id>", methods=["GET"])
def get_assignment(assignment_id):
    middleware.principal_for(ALL_ROLES)
    a = core.section_assignment(assignment_id)
    return envelope.ok(envelope.s_section_assignment(a), "object")


@bp.route("/section-assignments/<assignment_id>", methods=["PATCH"])
def reassign(assignment_id):
    middleware.principal_for(["KitchenLead"])
    a = core.section_assignment(assignment_id)
    data = middleware.body()
    section_service.reassign(a, data)
    return envelope.ok(envelope.s_section_assignment(a), "object")


@bp.route("/section-assignments/<assignment_id>/score", methods=["POST"])
def score(assignment_id):
    middleware.principal_for(["KitchenLead"])
    a = core.section_assignment(assignment_id)
    data = middleware.body()
    section_service.score(a, data)
    return envelope.ok(envelope.s_section_assignment(a), "object")


@bp.route("/section-assignments/<assignment_id>/close", methods=["POST"])
def close(assignment_id):
    middleware.principal_for(["KitchenLead"])
    a = core.section_assignment(assignment_id)
    section_service.close(a)
    return envelope.ok(envelope.s_section_assignment(a), "object")


@bp.route("/section-assignments/<assignment_id>/cancel", methods=["POST"])
def cancel(assignment_id):
    middleware.principal_for(["KitchenLead"])
    a = core.section_assignment(assignment_id)
    section_service.cancel(a)
    return envelope.ok(envelope.s_section_assignment(a), "object")