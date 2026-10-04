"""Test-driving logical clock endpoint (PRD 2.5)."""
from flask import Blueprint

from helpers import F, require_roles, respond, validate_body
from state import DB

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_current_utc():
    data = validate_body({"to_iso8601": F("dt", required=True)})
    DB.clock = data["to_iso8601"]
    return respond({"current_utc": DB.clock})
