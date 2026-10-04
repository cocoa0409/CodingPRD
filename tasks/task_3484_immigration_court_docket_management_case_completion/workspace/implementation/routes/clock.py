# routes/clock.py — POST /eoir/_clock/set_current_utc (CourtAdministrator).
from flask import Blueprint

import db
from auth import get_auth, require_role
from constants import ROLE_COURT_ADMINISTRATOR
from envelope import success
from inputs import get_body, req_datetime

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    get_auth_role = get_auth()
    require_role(get_auth_role[1], (ROLE_COURT_ADMINISTRATOR,))
    body = get_body()
    to_dt = req_datetime(body, "to_iso8601")
    db.set_clock(to_dt)
    # output: null -> empty object data per PRD §2.2
    return success({}, response_type="object", status=200)
