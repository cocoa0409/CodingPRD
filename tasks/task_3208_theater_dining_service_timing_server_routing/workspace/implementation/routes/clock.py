"""Logical clock test-driving endpoints."""

from flask import Blueprint

import db
import middleware
import response as envelope
from services import core
from services import disturbance as disturbance_service

bp = Blueprint("clock", __name__)

READ_ROLES = ["PlatformAdmin", "KitchenLead", "ProgrammingCoordinator", "PreShowProducer",
              "Server"]


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    middleware.principal_for(["PlatformAdmin"])
    data = middleware.body()
    target = db.parse_iso(data.get("to_iso8601"))
    if target is not None:
        db.db.now = target
    core.recompute_all_service_modes()
    core.reconcile_all_auditoriums()
    core.refresh_all_servers()
    disturbance_service.expire_stages()
    return envelope.ok({}, "object")


@bp.route("/_clock/current_utc", methods=["GET"])
def current_utc():
    middleware.principal_for(READ_ROLES)
    return envelope.ok({"current_utc": db.iso_z(db.db.now)}, "object")