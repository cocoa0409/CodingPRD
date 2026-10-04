"""The logical clock endpoint (PRD 2.5).

Mounted OUTSIDE the /atfm prefix: POST /_clock/set_current_utc. Before any set
call the clock reads exactly 2026-09-01T00:00:00Z and never falls back to
wall-clock time (see storage.get_clock).
"""

from flask import Blueprint

from constants import ROLE_SYSTEM_ADMINISTRATOR
from storage import get_clock, set_clock
from util import body_json, fmt_dt, req_dt, success_object
from validation import auth_context, require_roles

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_current_utc():
    auth_context()
    require_roles(ROLE_SYSTEM_ADMINISTRATOR)
    body = body_json()
    target = req_dt(body, "to_iso8601")
    set_clock(target)
    return success_object({"current_utc": fmt_dt(get_clock())})
