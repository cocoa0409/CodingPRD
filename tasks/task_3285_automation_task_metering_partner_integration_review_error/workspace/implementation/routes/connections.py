"""Connection routes and token-lapse injection."""
from flask import Blueprint, request

from clock import Clock
from common import account_or_404, connection_or_404
from db import db
from errors import ApiError
from middleware import require
from models import new_connection, new_lapse_incident, public, touch
from response import paginate, success
from services import connection_service

bp = Blueprint("connections", __name__)


@bp.route("/connections", methods=["POST"])
@require("Member")
def create_connection():
    body = request.get_json(silent=True) or {}
    account = account_or_404(body.get("account_id"))
    if db.integrations.get(body.get("integration_id")) is None:
        raise ApiError("ERR_INTEGRATION_NOT_FOUND")
    if db.members.get(body.get("owner_member_id")) is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND")
    rec = new_connection(account["id"], body)
    db.connections[rec["id"]] = rec
    return success(public(rec), 201)


@bp.route("/connections", methods=["GET"])
@require("Member", "PlatformAdmin")
def list_connections():
    account_id = request.args.get("account_id")
    owner_member_id = request.args.get("owner_member_id")
    items = [public(c) for c in db.connections.values()
             if (account_id is None or c["account_id"] == account_id)
             and (owner_member_id is None or c["owner_member_id"] == owner_member_id)]
    page, meta = paginate(items, request.args.get("limit"), request.args.get("offset"))
    return success(page, 200, pagination=meta)


@bp.route("/connections/<connection_id>", methods=["GET"])
@require("Member", "PlatformAdmin")
def read_connection(connection_id):
    return success(public(connection_or_404(connection_id)))


@bp.route("/connections/<connection_id>/refresh", methods=["POST"])
@require("Member")
def refresh_connection(connection_id):
    connection = connection_or_404(connection_id)
    body = request.get_json(silent=True) or {}
    rec = connection_service.refresh(connection, body.get("charge"))
    return success(public(rec))


@bp.route("/connections/<connection_id>/reauthorize", methods=["POST"])
@require("Member")
def reauthorize_connection(connection_id):
    connection = connection_or_404(connection_id)
    body = request.get_json(silent=True) or {}
    rec = connection_service.reauthorize(connection, body.get("charge"))
    return success(public(rec))


@bp.route("/connections/<connection_id>/disconnect", methods=["POST"])
@require("Member")
def disconnect_connection(connection_id):
    connection = connection_or_404(connection_id)
    body = request.get_json(silent=True) or {}
    rec = connection_service.disconnect(connection, body.get("charge"))
    return success(public(rec))


@bp.route("/_lapse/tokens/expire", methods=["POST"])
@require("PlatformAdmin")
def expire_token():
    body = request.get_json(silent=True) or {}
    connection = connection_or_404(body.get("connection_id"))
    # Expiring an already-lapsed credential is a no-op rather than an error: the
    # transition CONNECTED -> TOKEN_EXPIRED is attempted, and a connection that is
    # already TOKEN_EXPIRED simply stays there, so an operator may re-assert the
    # lapse deterministically (PRD §3.9).
    if connection["status"] == "DISCONNECTED":
        raise ApiError("ERR_CONNECTION_INVALID_STATE")
    Clock.event_no += 1
    connection["status"] = "TOKEN_EXPIRED"
    connection["token_expires_at"] = Clock.iso_now()
    touch(connection)
    incident = new_lapse_incident(Clock.event_no, Clock.iso_now(), "TOKEN_LAPSE",
                                  connection["id"])
    db.lapse_incidents[incident["id"]] = incident
    return success({
        "connection_id": connection["id"],
        "status": connection["status"],
        "token_expires_at": connection["token_expires_at"],
        "event_no": Clock.event_no,
    })


@bp.route("/_simulate/downstream-recover", methods=["POST"])
@require("PlatformAdmin")
def downstream_recover():
    body = request.get_json(silent=True) or {}
    connection = connection_or_404(body.get("connection_id"))
    connection["status"] = "CONNECTED"
    connection["reauth_requested_at"] = None
    touch(connection)
    Clock.event_no += 1
    incident = new_lapse_incident(Clock.event_no, Clock.iso_now(),
                                  "DOWNSTREAM_RECOVERY", connection["id"])
    db.lapse_incidents[incident["id"]] = incident
    released = [a["id"] for a in db.actions.values()
                if a["connection_id"] == connection["id"] and a["status"] == "HELD"]
    return success({
        "connection_id": connection["id"],
        "status": connection["status"],
        "released_held_action_ids": released,
    })