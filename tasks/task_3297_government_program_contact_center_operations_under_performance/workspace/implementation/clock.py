from datetime import datetime, timezone, timedelta
import uuid

# Logical clock state (module-level, reset per process)
_clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def now():
    return _clock


def set_clock(to_dt):
    global _clock
    _clock = to_dt


def parse_iso(s):
    """Parse an ISO-8601 string into an aware datetime (UTC). Accepts trailing Z."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    v = s.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_now():
    return isoformat(now())


def isoformat(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.astimezone(timezone.utc).microsecond // 1000:03d}Z"


def new_id():
    return str(uuid.uuid4())


def period_window(period):
    """Return (start_dt, end_dt) naive-local wall time as UTC-aware datetimes for YYYY-MM."""
    year, month = int(period[:4]), int(period[5:7])
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def period_end(period):
    return period_window(period)[1]


def plus_days(dt, days):
    return dt + timedelta(days=days)
