"""Test-driving logical clock."""

from registry import route
from utils import fmt_ts, parse_iso, set_clock, utc_now_dt


@route("POST", "/_clock/set_current_utc", roles=["PlatformAdmin"], status=200, write=True)
def set_current_utc(ctx):
    raw = ctx.body.get("current_utc")
    parsed = parse_iso(raw)
    if parsed is None:
        from errors import ApiError

        raise ApiError("ERR_INVALID_REQUEST", "current_utc must be an ISO 8601 instant")
    set_clock(parsed)
    return {"current_utc": fmt_ts(utc_now_dt())}