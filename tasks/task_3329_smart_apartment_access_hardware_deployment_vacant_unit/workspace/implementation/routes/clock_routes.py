"""Logical clock administration (PRD 3.10)."""

from db import clock, iso, parse_instant
from middleware import require_roles
from records import body, require_value, validate_body
from response import success
from svc_common import advance_clock


@require_roles("PlatformAdmin")
def set_current_utc(caller):
    payload = body()
    validate_body(payload, required=("current_utc",))
    moment = parse_instant(require_value(payload, "current_utc"), "current_utc")
    clock.set(moment)
    advance_clock(moment)
    return success({}, "object", 200)


API_ROUTES = [
    ("POST", "/_clock/set_current_utc", set_current_utc),
]