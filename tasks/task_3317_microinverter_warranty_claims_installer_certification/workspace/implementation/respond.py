"""Response envelope, identifier/timestamp minting, the logical clock, and
calendar-exact month arithmetic.

Envelope shape is fixed by PRD section 2.2; pagination field names and bounds by
section 2.3.
"""

import re
import uuid
from datetime import datetime, timedelta, timezone

from flask import jsonify

# ---------------------------------------------------------------- logical clock

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"


class Clock:
    """The one clock every age, expiry, band and window rule reads.

    It starts at the fixed default instant and never falls back to wall-clock
    time (PRD section 2.7).
    """

    def __init__(self):
        self._now = _parse_iso(DEFAULT_CLOCK)

    def now(self):
        return self._now

    def set(self, to_iso8601):
        self._now = _parse_iso(to_iso8601)


# The singleton is created after the parsing helpers below are defined, so the
# constructor can call them; see CLOCK = Clock() at the foot of this section.


# ------------------------------------------------------------------ identifiers


def new_id():
    """Server-minted UUID, no type prefix, no embedded business meaning."""
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:20].upper()


# ------------------------------------------------------------------- timestamps


def iso(dt):
    """ISO 8601 UTC instant with three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso(CLOCK.now())


_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}")


def _parse_iso(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str) or not _ISO_RE.match(value.strip()):
        raise ValueError("not an ISO 8601 instant: %r" % (value,))
    text = value.strip().replace(" ", "T")
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso(value):
    """Parse a client-supplied instant; malformed input raises ValueError."""
    return _parse_iso(value)


def is_iso(value):
    try:
        parse_iso(value)
        return True
    except (ValueError, TypeError):
        return False


CLOCK = Clock()


# ------------------------------------------------------------- month arithmetic

_DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)


def _days_in_month(year, month):
    if month == 2 and (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)):
        return 29
    return _DAYS_IN_MONTH[month - 1]


def add_months(dt, months):
    """Calendar-exact month arithmetic, clamping the day to the target month."""
    months = int(months)
    total = dt.year * 12 + (dt.month - 1) + months
    year, month = divmod(total, 12)
    month += 1
    day = min(dt.day, _days_in_month(year, month))
    return dt.replace(year=year, month=month, day=day)


def whole_months_between(start, end):
    """Whole months elapsed from start to end; negative when end precedes start."""
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day < start.day:
        months -= 1
    return months


def months_between_floor_zero(start, end):
    return max(0, whole_months_between(start, end))


def supersede_updated_at(record):
    """Stamp updated_at and bump version on the audited entities."""
    if record is None:
        return
    if "updated_at" in record:
        record["updated_at"] = now_iso()
    if "version" in record:
        record["version"] = int(record.get("version", 0)) + 1


# ------------------------------------------------------------ response envelope


def _meta(request_id=None, pagination=None):
    meta = {
        "api_request_id": request_id or new_request_id(),
        "api_request_timestamp": now_iso(),
    }
    if pagination:
        meta.update(pagination)
    return meta


def ok(data, status=200, pagination=None, request_id=None):
    """Single-resource success envelope."""
    return jsonify({
        "meta": _meta(request_id, pagination),
        "response_type": "object",
        "data": data if data is not None else {},
    }), status


def ok_list(items, status=200, pagination=None, request_id=None):
    """Array success envelope."""
    return jsonify({
        "meta": _meta(request_id, pagination),
        "response_type": "array",
        "data": items,
    }), status


def error_body(error_id, message, request_id=None):
    return {
        "meta": {
            "api_request_id": request_id or new_request_id(),
            "api_request_timestamp": now_iso(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------- pagination

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def pagination_meta(total, returned):
    """The pagination block of a list response, per PRD 2.3."""
    return {
        "limit": returned,
        "offset": 0,
        "total_count": total,
        "has_more": False,
    }


def paginate(items, args):
    """Apply limit/offset and return (window, meta-fields).

    Limit defaults to 10 with a minimum of 1 and a maximum of 100; a value
    outside that range, or a non-integer, is a malformed request body (PRD 2.3).
    """
    from errors import fail

    raw_limit = args.get("limit")
    raw_offset = args.get("offset")

    if raw_limit is None or raw_limit == "":
        limit = PAGE_LIMIT_DEFAULT
    else:
        try:
            limit = int(str(raw_limit))
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST_BODY", "pagination parameter `limit` is not an integer")
    if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
        fail("ERR_INVALID_REQUEST_BODY", "pagination parameter `limit` is out of range")

    if raw_offset is None or raw_offset == "":
        offset = PAGE_OFFSET_DEFAULT
    else:
        try:
            offset = int(str(raw_offset))
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST_BODY", "pagination parameter `offset` is not an integer")
    if offset < 0:
        fail("ERR_INVALID_REQUEST_BODY", "pagination parameter `offset` is negative")

    total = len(items)
    window = items[offset:offset + limit]
    return window, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }