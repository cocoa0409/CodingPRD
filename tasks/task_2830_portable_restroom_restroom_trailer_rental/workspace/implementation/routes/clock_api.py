"""Logical-clock repositioning and the permit-expiry sweep it triggers."""
from flask import Blueprint

from auth import endpoint
import clock
from responses import ok
import services
import validation as V

bp = Blueprint("clock_api", __name__)


@bp.post("/_clock/set_current_utc")
@endpoint(["PlatformAdmin"])
def set_current_utc():
    body = V.body()
    to_iso8601 = V.str_field(body, "to_iso8601", 1)
    instant = clock.parse_instant(to_iso8601)
    if instant is None:
        V.bad("Field 'to_iso8601' must be an ISO 8601 instant.")

    clock.set_now(instant)
    expired, blocked, suspended = services.expire_permits_sweep()
    return ok({
        "current_utc": clock.now_iso(),
        "expired_permit_count": expired,
        "blocked_site_count": blocked,
        "suspended_schedule_count": suspended,
    })
