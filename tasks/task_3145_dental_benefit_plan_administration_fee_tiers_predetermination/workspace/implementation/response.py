"""Response envelope and time helpers per PRD §2.2/§2.3/§2.4.

- Success envelope: {meta, response_type, data}; list responses also carry
  limit/offset/total_count/has_more inside meta.
- Error envelope: {meta: {api_request_id, api_request_timestamp},
  response_type: "error", data: {error_id, message}}.
- api_request_id starts with "req_" and api_request_timestamp is ISO 8601
  UTC with three fractional digits.
"""

import re
import uuid
from datetime import datetime, timezone

from flask import jsonify

_ISO8601_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})$"
)


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex[:24]


def iso_now():
    """Server-minted creation timestamps use wall-clock UTC, 3 fractional digits."""
    return format_iso(datetime.now(timezone.utc))


def format_iso(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def parse_iso(value):
    """Parse an ISO 8601 timestamp; returns a tz-aware datetime or None."""
    if not isinstance(value, str):
        return None
    if not _ISO8601_RE.match(value):
        return None
    s = value.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def success_object(data, status=200):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": iso_now(),
        },
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def success_list(items, total_count, limit, offset):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": iso_now(),
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        },
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": new_request_id(),
            "api_request_timestamp": iso_now(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


def parse_pagination(args):
    """Parse limit/offset query params per PRD §2.3.

    Defaults: limit=10 (min 1, max 100), offset=0.
    """
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        offset = 0
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset
