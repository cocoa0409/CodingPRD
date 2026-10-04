"""POST /_clock/set_current_utc — PlatformAdmin advances the logical clock
(PRD 2.4). Returns the clock's new reading. Lazy transitions (quote EXPIRED,
cert LAPSED) evaluate on subsequent reads/writes.
"""
from flask import Blueprint

from core import clock
from core.auth import authenticate, require_role
from core.constants import ROLE_PLATFORM_ADMIN
from core.envelope import success_object
from core.validate import get_body, req_dt

bp = Blueprint("clock", __name__)


@bp.post("/_clock/set_current_utc")
def set_current_utc():
    _, role = authenticate()
    require_role(role, ROLE_PLATFORM_ADMIN)
    body = get_body()
    current_utc = req_dt(body, "current_utc")
    clock.set_now(current_utc)
    return success_object({"current_utc": clock.fmt_instant(clock.now())})
