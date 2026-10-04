"""Logical clock endpoint (PRD 2.10)."""

from flask import Blueprint

from services import compliance
from routes.helpers import endpoint, ok

bp = Blueprint("clock_routes", __name__)

BLUEPRINTS = [bp]


@bp.route("/_clock/set_current_utc", methods=["POST"])
@endpoint("POST", "/_clock/set_current_utc")
def set_current_utc(caller, body):
    return ok(lambda payload: payload, compliance.set_current_utc(body))