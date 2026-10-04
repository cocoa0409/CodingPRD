"""Logical clock test-driving capability (PRD 2.5)."""
from flask import Blueprint

import store
from auth import caller, require_role
from constants import ROLE_PLATFORM_ADMIN
from derived import sweep_eso_expiry
from envelope import ok
from errors import api_err
from timeutil import parse_instant
from validate import json_body, req_str

bp = Blueprint('clock', __name__)


@bp.post('/stb/_clock/set_current_utc')
def set_current_utc():
    _uid, role = caller()
    data = json_body()
    current_utc = req_str(data, 'current_utc')
    parsed = parse_instant(current_utc)
    if parsed is None:
        raise api_err('ERR_INVALID_REQUEST', 'current_utc must be a valid ISO-8601 UTC instant')
    require_role(role, (ROLE_PLATFORM_ADMIN,))
    dt, frac = parsed
    store.set_clock(dt, frac)
    # Advancing the clock applies any emergency-service-order expirations.
    sweep_eso_expiry()
    return ok({}, 200)
