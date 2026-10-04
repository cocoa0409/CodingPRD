"""Response envelope helpers.

The envelope is fixed by PRD section 2.2 and SCAFFOLD section 1.0:

  { "meta": { "api_request_id", "api_request_timestamp", ... },
    "response_type": "object" | "array" | "error",
    "data": {} }
"""

import random
import string
from datetime import datetime, timedelta, timezone

from errors import ApiError

_ALPHABET = string.ascii_uppercase + string.digits


def request_id():
    body = "".join(random.choice(_ALPHABET) for _ in range(18))
    return "req_" + body


def envelope_timestamp(now=None):
    """ISO 8601 UTC with exactly three fractional digits."""
    if now is None:
        now = datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def _meta(pagination=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": envelope_timestamp(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok(data, pagination=None):
    """200 with the resource object in data."""
    return {"meta": _meta(pagination), "response_type": "object", "data": data}, 200


def created(data, pagination=None):
    return {"meta": _meta(pagination), "response_type": "object", "data": data}, 201


def array(items, pagination=None):
    """200 with a page of resources in data."""
    if pagination is None:
        pagination = {
            "limit": 10,
            "offset": 0,
            "total_count": len(items),
            "has_more": False,
        }
    return {"meta": _meta(pagination), "response_type": "array", "data": items}, 200


def error_body(exc):
    body = {
        "meta": {
            "api_request_id": request_id(),
            "api_request_timestamp": envelope_timestamp(),
        },
        "response_type": "error",
        "data": {"error_id": exc.error_id, "message": exc.message},
    }
    return body


def paginate(items, limit, offset):
    """Apply limit/offset and return (page, pagination_meta)."""
    limit = pagination_limit(limit)
    offset = pagination_offset(offset)
    total = len(items)
    page = items[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }


def pagination_limit(raw):
    if raw is None or raw == "":
        return 10
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
    if value < 1 or value > 100:
        raise ApiError("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    return value


def pagination_offset(raw):
    if raw is None or raw == "":
        return 0
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
    if value < 0:
        raise ApiError("ERR_INVALID_REQUEST", "offset must not be negative.")
    return value


def as_bool(raw, default=False):
    if raw is None or raw == "":
        return default
    if isinstance(raw, bool):
        return raw
    return str(raw).lower() in ("true", "1", "yes")


def sort_by_created(rows):
    return sorted(rows, key=lambda row: (row.get("created_at") or "", row.get("id") or ""))