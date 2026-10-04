"""POST /reemployment/_clock/set_current_utc — the test-driving clock endpoint."""
from flask import Blueprint

from auth import require_role
from helpers import body_json, req_dt
from store import db
from util import success

bp = Blueprint("clock", __name__)


@bp.route("/reemployment/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    require_role("ProgramCoordinator")
    body = body_json()
    to = req_dt(body, "to_iso8601")
    db.clock = to
    return success({}, "object", 200)
