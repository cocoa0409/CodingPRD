"""Shared helpers: envelope, timestamps, ids, rounding, errors, parsing."""
import re
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from db import get_clock

CODE_VALUE_RE = re.compile(r"^[A-Z][0-9A-Z.]{2,15}$")


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def bad_request(msg):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def unauthorized(msg):
    return ApiError("ERR_UNAUTHORIZED", 403, msg)


def not_found(msg):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def invalid_state(msg):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def stale_version(msg):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + uuid.uuid4().hex[:24]


def now_ts():
    """Current logical timestamp, ISO 8601 UTC with three fractional digits."""
    dt = get_clock()
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def wall_ts():
    """Wall-clock UTC timestamp (for meta.api_request_timestamp)."""
    dt = datetime.now(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def round_half_up_int(value):
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_4(value):
    return float(Decimal(str(value)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


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


def is_bool(v):
    return isinstance(v, bool)


def is_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))


def parse_iso8601_utc(s):
    """Parse an ISO8601 UTC instant; returns aware datetime or None on bad format."""
    if not is_string(s):
        return None
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    """Render an aware UTC datetime to ISO 8601 with three fractional digits."""
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def get_entity(store_name, entity_id, label=None):
    from db import stores
    ent = stores[store_name].get(entity_id)
    if ent is None:
        raise not_found("%s not found: %s" % (label or store_name, entity_id))
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
    return sorted(items, key=lambda e: e["created_at"])
