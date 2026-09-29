"""POST /_clock/set_current_utc — the logical clock."""
from flask import Blueprint

from common import (ALL_ROLES, authorize, body_json, fmt_instant, need_instant,
                    respond_object, set_clock)

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    authorize(ALL_ROLES)
    body = body_json()
    current_utc = need_instant(body, "current_utc")
    previous = set_clock(current_utc)
    return respond_object({
        "current_utc": fmt_instant(current_utc),
        "previous_utc": fmt_instant(previous),
    }, 200)
