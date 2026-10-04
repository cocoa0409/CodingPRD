"""The logical clock control surface (PRD section 2.9)."""

from flask import Blueprint

import db
from errors import raise_error
from middleware import require_role
from response import ok_empty
from routes.common import body
from services import channel as channel_svc

bp = Blueprint("clock", __name__, url_prefix="/api")


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_role("PlatformAdmin")
    payload = body()

    target = db.parse_iso8601(payload.get("to_iso8601"))
    if target is None:
        raise_error("ERR_INVALID_STATE", "to_iso8601 must be a valid ISO 8601 instant.")

    db.set_clock(target)
    # Advancing the clock is not passive: it runs the strike expiry sweep.
    channel_svc.run_strike_expiry_sweep()
    return ok_empty()