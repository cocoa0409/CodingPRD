"""Logical clock endpoint (PRD section 2.4).

Mounted INSIDE the /eeoc prefix exactly as the PRD endpoint table states.
"""

from flask import Blueprint

import constants
from helpers import (
    authenticate,
    iso_dt_flexible,
    request_body,
    require_roles,
    respond_object,
)
from store import db
from validation import req_datetime

bp = Blueprint("clock", __name__, url_prefix="/eeoc")


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _, role = authenticate()
    require_roles(role, (constants.ROLE_PLATFORM_ADMIN,))
    body = request_body()
    target = req_datetime(body, "to_iso8601")
    db.clock = target
    return respond_object({"current_utc": iso_dt_flexible(db.clock)}, status=200)
