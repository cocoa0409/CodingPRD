"""Logical clock + shared utilities."""
import re
import uuid
from datetime import datetime, date, timedelta, timezone

from errors import raise_error, ERR_INVALID_REQUEST, ERR_INVALID_DATE_RANGE

_DEFAULT_CLOCK = "2026-09-01T00:00:00Z"

_current_clock_iso = _DEFAULT_CLOCK


def get_clock_dt():
    """Logical clock as aware datetime (UTC)."""
    return datetime.fromisoformat(_current_clock_iso.replace("Z", "+00:00")).astimezone(timezone.utc)


def get_clock_date():
    return get_clock_dt().date()


def set_clock(iso_str):
    global _current_clock_iso
    dt = _parse_instant(iso_str)
    _current_clock_iso = _fmt_clock(dt)
    return _current_clock_iso


def clock_iso():
    return _current_clock_iso


def _fmt_clock(dt):
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_instant(s):
    if not isinstance(s, str):
        raise_error(ERR_INVALID_REQUEST, "expected ISO8601 timestamp string")
    txt = s.strip()
    try:
        if txt.endswith("Z"):
            dt = datetime.fromisoformat(txt[:-1] + "+00:00")
        else:
            dt = datetime.fromisoformat(txt)
    except ValueError:
        raise_error(ERR_INVALID_REQUEST, "unparsable ISO8601 timestamp")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def now_ts():
    """Mutation timestamp from the logical clock, three fractional digits."""
    dt = get_clock_dt()
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "000Z"


def new_id():
    return str(uuid.uuid4())


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_date(value, field="date"):
    """Parse an ISO calendar date string. Raises ERR_INVALID_DATE_RANGE on failure."""
    if not isinstance(value, str) or not _DATE_RE.match(value.strip()):
        raise_error(ERR_INVALID_DATE_RANGE, f"{field} is not a valid ISO date")
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise_error(ERR_INVALID_DATE_RANGE, f"{field} is not a valid ISO date")


def require_fields(payload, fields):
    if not isinstance(payload, dict):
        raise_error(ERR_INVALID_REQUEST, "request body must be a JSON object")
    for f in fields:
        if f not in payload or payload[f] is None:
            raise_error(ERR_INVALID_REQUEST, f"missing required field: {f}")


def require_non_empty_str(payload, field):
    v = payload.get(field)
    if not isinstance(v, str) or not v.strip():
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be a non-empty string")
    return v


def optional_str(payload, field, default=None):
    v = payload.get(field, default)
    if v is not None and not isinstance(v, str):
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be a string")
    return v


def require_int(payload, field):
    v = payload.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise_error(ERR_INVALID_REQUEST, f"field {field} must be an integer")
    return v


def touch(obj):
    """Refresh updated_at and bump version where present."""
    obj["updated_at"] = now_ts()
    if "version" in obj:
        obj["version"] += 1
