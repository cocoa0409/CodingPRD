"""Shared helpers: envelope, timestamps, ids, rounding, errors, logical clock parsing."""
import re
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import get_clock

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def bad_request(msg):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def err_unauthenticated(msg):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def err_forbidden(msg):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def not_found(error_id, msg):
    return ApiError(error_id, 404, msg)


def conflict(error_id, msg):
    return ApiError(error_id, 409, msg)


def unprocessable(error_id, msg):
    return ApiError(error_id, 422, msg)


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + uuid.uuid4().hex[:24]


def now_ts():
    """Current logical timestamp, ISO 8601 UTC with three fractional digits."""
    dt = get_clock()
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms

def fmt_ts(dt):
    """Format a UTC datetime: three fractional digits, omitted when exactly zero.

    The logical clock's initial value (2026-09-01T00:00:00Z) and clock-set values
    are recorded exactly as the ISO-8601 instants the PRD names; sub-second
    precision is rendered with millisecond fractional digits.
    """
    ms = dt.microsecond // 1000
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return base + "Z" if ms == 0 else base + ".%03dZ" % ms


def clock_ts():
    """Current logical timestamp as an exact ISO-8601 UTC instant."""
    return fmt_ts(get_clock())


def _ts(dt):
    return fmt_ts(dt)


def wall_ts():
    """Wall-clock UTC timestamp (for meta.api_request_timestamp), three fractional digits."""
    dt = datetime.now(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def current_date():
    return get_clock().date()


def round_half_up_int(value):
    """Round a Decimal/numeric to the nearest integer, half-up."""
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def get_body():
    """Parse the request JSON body; ERR_INVALID_REQUEST if malformed."""
    from flask import request
    if request.data is None or len(request.data) == 0:
        return {}
    try:
        body = request.get_json(force=False, silent=False)
    except Exception:
        raise bad_request("Request body is not valid JSON")
    if body is None:
        raise bad_request("Request body is not valid JSON")
    if not isinstance(body, dict):
        raise bad_request("Request body must be a JSON object")
    return body


def require_fields(body, fields):
    for f in fields:
        if f not in body or body[f] is None:
            raise bad_request("Missing required field: %s" % f)


def is_string(v):
    return isinstance(v, str)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def check_date_str(v, field):
    if not is_string(v) or not DATE_RE.match(v):
        raise bad_request("%s must be YYYY-MM-DD" % field)
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise bad_request("%s must be a valid YYYY-MM-DD date" % field)


def parse_iso8601_utc(s, field="to_iso8601"):
    """Parse an ISO8601 UTC instant. Raises ERR_INVALID_REQUEST on bad format."""
    if not is_string(s):
        raise bad_request("%s must be an ISO8601 string" % field)
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise bad_request("%s must be a valid ISO8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_entity(store_name, entity_id, error_id, label=None):
    from db import stores
    ent = stores[store_name].get(entity_id)
    if ent is None:
        raise not_found(error_id, "%s not found: %s" % (label or store_name, entity_id))
    return ent


def touch(entity):
    """Refresh updated_at and bump version by exactly 1."""
    entity["updated_at"] = now_ts()
    entity["version"] += 1


def new_entity(extra=None):
    ts = now_ts()
    e = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}
    if extra:
        e.update(extra)
    return e


def paginate(items):
    """Apply limit/offset pagination; returns (page, meta-fields dict)."""
    from flask import request
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise bad_request("limit must be an integer")
        if limit < 1 or limit > 100:
            raise bad_request("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise bad_request("offset must be an integer")
        if offset < 0:
            raise bad_request("offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return page, {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}


def sort_created(items):
    """Default sort: created_at ASC. Ties preserve insertion order (stable sort)."""
    return sorted(items, key=lambda e: e["created_at"])
