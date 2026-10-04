"""Server-managed logical clock. Starts at exactly 2026-09-01T00:00:00Z and
never falls back to wall-clock time. Advances only via set() (NetworkAdmin)."""
from datetime import datetime, timezone


_INITIAL = "2026-09-01T00:00:00Z"


class _ClockState:
    current = None


def _parse_iso(value):
    """Parse an ISO 8601 datetime (Z or offset) into an aware UTC datetime."""
    s = str(value)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def init_clock():
    _ClockState.current = _parse_iso(_INITIAL)


def now():
    return _ClockState.current


def set_current(value):
    _ClockState.current = _parse_iso(value)
    return _ClockState.current


def format_dt(dt):
    """Format an aware UTC datetime as ISO 8601 with three fractional digits."""
    s = dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03d" % (dt.microsecond // 1000)
    return s + "Z"


def now_str():
    return format_dt(now())


def today_date():
    return now().date()
