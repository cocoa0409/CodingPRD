"""Test-driving logical clock endpoint (outside the /licensing prefix)."""
from flask import Blueprint

import store
from helpers import as_dt, body, req_field, require_roles, success

bp = Blueprint("clock", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
@require_roles("PlatformAdmin")
def set_current_utc():
    b = body()
    current_utc = as_dt(req_field(b, "current_utc"), "current_utc")
    store.clock_set(current_utc)
    return success({}, code=200)
