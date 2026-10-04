"""Parsing and request-shape validation helpers.

All shape failures raise ERR_INVALID_REQUEST (400) per PRD 2.8 priority 9.
Dates are strict YYYY-MM-DD; datetimes are strict ISO 8601 UTC forms with
seconds (optional fractional digits, Z or numeric offset).
"""

import re
from calendar import monthrange
from datetime import date, datetime, timezone

from flask import request

import constants
from errors import fail

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|[+-]\d{2}:\d{2})$")


def parse_date(s):
    """Strict YYYY-MM-DD -> date, or None when malformed/impossible."""
    if not isinstance(s, str) or not _DATE_RE.match(s):
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_datetime(s):
    """ISO 8601 datetime -> aware UTC datetime, or None when malformed."""
    if not isinstance(s, str) or not _DT_RE.match(s):
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.astimezone(timezone.utc)


def format_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.5)."""
    return f"{dt:%Y-%m-%dT%H:%M:%S}.{dt.microsecond // 1000:03d}Z"


def add_months(d, months):
    """Add calendar months to a date, clamping the day to the month length."""
    total = (d.year * 12 + (d.month - 1)) + months
    year, month0 = divmod(total, 12)
    month = month0 + 1
    day = min(d.day, monthrange(year, month)[1])
    return date(year, month, day)


def weekday_code(d):
    return constants.DAY_CODES[d.weekday()]


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def body():
    """JSON request body as a dict; absent/malformed/non-object -> {} (the
    missing-field failures then surface as ERR_INVALID_REQUEST at the shape
    stage, keeping the PRD 2.8 pipeline order)."""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def req_field(b, name):
    v = b.get(name)
    if v is None:
        fail("ERR_INVALID_REQUEST", f"Missing required field: {name}")
    return v


def req_str(b, name):
    v = req_field(b, name)
    if not isinstance(v, str):
        fail("ERR_INVALID_REQUEST", f"Field {name} must be a string")
    return v


def req_bool(b, name):
    v = req_field(b, name)
    if not isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", f"Field {name} must be a boolean")
    return v


def opt_bool(b, name, default):
    v = b.get(name)
    if v is None:
        return default
    if not isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", f"Field {name} must be a boolean")
    return v


def req_int(b, name, minimum=None, maximum=None):
    v = req_field(b, name)
    if not is_int(v):
        fail("ERR_INVALID_REQUEST", f"Field {name} must be an integer")
    if minimum is not None and v < minimum:
        fail("ERR_INVALID_REQUEST", f"Field {name} must be >= {minimum}")
    if maximum is not None and v > maximum:
        fail("ERR_INVALID_REQUEST", f"Field {name} must be <= {maximum}")
    return v


def req_date(b, name):
    """Required ISO date field; returns the raw (already strict) string."""
    raw = req_str(b, name)
    if parse_date(raw) is None:
        fail("ERR_INVALID_REQUEST", f"Field {name} must be a valid YYYY-MM-DD date")
    return raw


def req_datetime(b, name):
    """Required ISO 8601 datetime field; returns (raw_string, parsed_utc)."""
    raw = req_str(b, name)
    parsed = parse_datetime(raw)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", f"Field {name} must be a valid ISO 8601 UTC datetime")
    return raw, parsed


def req_enum(b, name, allowed):
    v = req_str(b, name)
    if v not in allowed:
        fail("ERR_INVALID_REQUEST", f"Field {name} must be one of {list(allowed)}")
    return v


def pagination():
    """Parse limit/offset per PRD 2.3 (default 10/0, limit within 1..100)."""
    args = request.args
    raw_limit = args.get("limit")
    if raw_limit is None:
        limit = constants.PAGE_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < constants.PAGE_MIN_LIMIT or limit > constants.PAGE_MAX_LIMIT:
            fail("ERR_INVALID_REQUEST", "limit out of range")
    raw_offset = args.get("offset")
    if raw_offset is None:
        offset = constants.PAGE_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset
