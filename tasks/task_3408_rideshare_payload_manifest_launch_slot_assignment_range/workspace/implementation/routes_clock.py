"""POST /_clock/set_current_utc — move the logical clock, run expiry sweep."""
from flask import Blueprint

from cascade import expiry_sweep
from envelope import success
from middleware import require_roles
from store import set_clock
from validate import as_dt, body_json, req_field

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
@require_roles("PlatformAdmin")
def set_current_utc():
    body = body_json()
    raw = req_field(body, "current_utc")
    current = as_dt(raw, "current_utc")
    set_clock(current)
    expiry_sweep()
    # "the response body echoes the accepted current_utc"
    return success({"current_utc": raw})
