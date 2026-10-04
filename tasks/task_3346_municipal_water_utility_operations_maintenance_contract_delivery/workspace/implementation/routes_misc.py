"""Logical clock capability — PRD 2.5."""
from core import CLOCK, body, endpoint, field, iso, parse_dt


@endpoint("/_clock/set_current_utc", ["POST"], ["PlatformAdmin"])
def set_current_utc():
    to_iso8601 = parse_dt(field(body(), "to_iso8601"))
    CLOCK["now"] = to_iso8601
    return {"current_utc": iso(to_iso8601)}
