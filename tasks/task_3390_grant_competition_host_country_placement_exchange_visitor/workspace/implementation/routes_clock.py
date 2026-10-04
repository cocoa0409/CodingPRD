"""Test-driving logical clock endpoint (PlatformAdmin only)."""

from flask import Blueprint

import envelope
from auth import auth, require_roles
from constants import ROLE_PLATFORM_ADMIN
from store import STORE
from validate import body, check_unknown, req, as_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _, role = auth()
    require_roles(role, [ROLE_PLATFORM_ADMIN])
    payload = body()
    check_unknown(payload, {"to_iso8601"})
    STORE.clock = as_dt(req(payload, "to_iso8601"), "to_iso8601")
    return envelope.ok({}, 200)
