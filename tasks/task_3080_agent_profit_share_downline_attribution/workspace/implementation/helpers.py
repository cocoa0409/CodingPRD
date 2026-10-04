"""Shared helpers: errors, envelope primitives, timestamps, rounding, parsing."""
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import get_clock

PERIOD_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def validation(msg):
    return ApiError("ERR_VALIDATION", 400, msg)


def not_found(error_id, msg):
    return ApiError(error_id, 404, msg)


def invalid_state(msg):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + uuid.uuid4().hex[:24]


def _fmt_ms(dt):
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def now_ts():
    """Current logical timestamp, ISO 8601 UTC with three fractional digits."""
    return _fmt_ms(get_clock())


def wall_ts():
    """Wall-clock UTC timestamp (meta.api_request_timestamp), three fractional digits."""
    return _fmt_ms(datetime.now(timezone.utc))


def round2(value):
    """Round to 2 decimal places, half-up. Returns float."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def round4(value):
    """Round to 4 decimal places, half-up. Returns float."""
    return float(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def d2(value):
    """Decimal rounded to 2dp half-up."""
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def parse_ts(value, field):
    """Parse an ISO8601 timestamp (accepts trailing Z or offset). ERR_VALIDATION if bad."""
    if not isinstance(value, str):
        raise validation("%s must be an ISO8601 string" % field)
    txt = value.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise validation("%s must be a valid ISO8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_out(dt):
    return _fmt_ms(dt)


def get_body():
    """Parse the request JSON body; ERR_VALIDATION if malformed."""
    from flask import request
    if request.data is None or len(request.data) == 0:
        return {}
    try:
        body = request.get_json(force=False, silent=False)
    except Exception:
        raise validation("Request body is not valid JSON")
    if body is None:
        raise validation("Request body is not valid JSON")
    if not isinstance(body, dict):
        raise validation("Request body must be a JSON object")
    return body


def is_string(v):
    return isinstance(v, str)


def is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def require_string(body, field):
    v = body.get(field)
    if v is None:
        raise validation("Missing required field: %s" % field)
    if not is_string(v) or v == "":
        raise validation("%s must be a non-empty string" % field)
    return v


def require_number(body, field):
    v = body.get(field)
    if v is None:
        raise validation("Missing required field: %s" % field)
    if not is_number(v):
        raise validation("%s must be a number" % field)
    return v


def new_entity(extra=None):
    ts = now_ts()
    e = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}
    if extra:
        e.update(extra)
    return e


def touch(entity):
    """Refresh updated_at and bump version by exactly 1."""
    entity["updated_at"] = now_ts()
    entity["version"] += 1


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
            raise validation("limit must be an integer")
        if limit < 1 or limit > 100:
            raise validation("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise validation("offset must be an integer")
        if offset < 0:
            raise validation("offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return page, {"limit": limit, "offset": offset, "total_count": total,
                  "has_more": has_more}


def sort_created(items):
    """Default sort: created_at ASC (stable for ties)."""
    return sorted(items, key=lambda e: e["created_at"])
