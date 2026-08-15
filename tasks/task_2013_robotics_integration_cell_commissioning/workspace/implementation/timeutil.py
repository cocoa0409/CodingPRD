"""Timestamp helpers: ISO 8601 UTC with three fractional digits (PRD §2.4)."""
from datetime import datetime, timezone

from errors import bad_request


def fmt_dt(dt):
    """Format an aware datetime as ISO 8601 UTC with millisecond precision."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_iso():
    """Wall-clock timestamp for created_at/updated_at/api_request_timestamp."""
    return fmt_dt(datetime.now(timezone.utc))


def parse_dt(value, field):
    """Parse an ISO 8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str) or not value.strip():
        raise bad_request(f"Field '{field}' must be an ISO 8601 datetime string")
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise bad_request(f"Field '{field}' is not a valid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
