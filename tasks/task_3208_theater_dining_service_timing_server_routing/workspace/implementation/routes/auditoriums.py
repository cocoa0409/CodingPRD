"""Auditorium routes, including the derived posture and liability reads."""

from flask import Blueprint, request

import db
import middleware
import response as envelope
from services import auditorium as auditorium_service
from services import core

bp = Blueprint("auditoriums", __name__)

ALL_ROLES = ["PlatformAdmin", "KitchenLead", "ProgrammingCoordinator", "PreShowProducer",
             "Server"]
POSTURE_ROLES = ["PlatformAdmin", "KitchenLead", "Server"]


@bp.route("/auditoriums", methods=["POST"])
def create_auditorium():
    middleware.principal_for(["PlatformAdmin"])
    data = middleware.body()
    row = auditorium_service.create(data)
    return envelope.ok(envelope.s_auditorium(row), "object", 201)


@bp.route("/auditoriums", methods=["GET"])
def list_auditoriums():
    middleware.principal_for(ALL_ROLES)
    rows = db.db.sorted_rows("auditoriums")
    limit, offset = middleware.pagination()
    return envelope.ok_list(rows, limit, offset, len(rows), envelope.s_auditorium)


@bp.route("/auditoriums/<aud_id>", methods=["GET"])
def get_auditorium(aud_id):
    middleware.principal_for(ALL_ROLES)
    aud = core.auditorium(aud_id)
    core.reconcile_auditorium(aud)
    return envelope.ok(envelope.s_auditorium(aud), "object")


@bp.route("/auditoriums/<aud_id>/posture", methods=["GET"])
def get_posture(aud_id):
    middleware.principal_for(POSTURE_ROLES)
    aud = core.auditorium(aud_id)
    return envelope.ok(auditorium_service.posture(aud), "object")


@bp.route("/auditoriums/<aud_id>/activate", methods=["POST"])
def activate(aud_id):
    middleware.principal_for(["PlatformAdmin"])
    aud = core.auditorium(aud_id)
    auditorium_service.activate(aud)
    return envelope.ok(envelope.s_auditorium(aud), "object")


@bp.route("/auditoriums/<aud_id>/close", methods=["POST"])
def close(aud_id):
    middleware.principal_for(["PlatformAdmin"])
    aud = core.auditorium(aud_id)
    auditorium_service.close(aud)
    return envelope.ok(envelope.s_auditorium(aud), "object")


@bp.route("/auditoriums/<aud_id>/refund-liability", methods=["GET"])
def refund_liability(aud_id):
    middleware.principal_for(["PlatformAdmin", "KitchenLead"])
    aud = core.auditorium(aud_id)
    return envelope.ok(auditorium_service.refund_liability(aud), "object")


@bp.route("/auditoriums/<aud_id>/showtimes", methods=["GET"])
def list_showtimes(aud_id):
    middleware.principal_for(ALL_ROLES)
    core.auditorium(aud_id)
    status = request.args.get("status")
    rows = [s for s in db.db.sorted_rows("showtimes")
            if s["auditorium_id"] == aud_id and (status is None or s["status"] == status)]
    limit, offset = middleware.pagination()
    return envelope.ok_list(rows, limit, offset, len(rows), envelope.s_showtime)


@bp.route("/auditoriums/<aud_id>/programming-events", methods=["GET"])
def list_programming_events(aud_id):
    middleware.principal_for(ALL_ROLES)
    core.auditorium(aud_id)
    status = request.args.get("status")
    rows = [e for e in db.db.sorted_rows("programming_events")
            if e["auditorium_id"] == aud_id and (status is None or e["status"] == status)]
    limit, offset = middleware.pagination()
    return envelope.ok_list(rows, limit, offset, len(rows), envelope.s_programming_event)