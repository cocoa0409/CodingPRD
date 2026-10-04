"""Response envelope helpers (SCAFFOLD.yaml §1.0 / PRD §2.2).

Success: {"meta": {"api_request_id", "api_request_timestamp"[, pagination]},
          "response_type": "object" | "array", "data": ...}
Error:   {"meta": {"api_request_id", "api_request_timestamp"},
          "response_type": "error", "data": {"error_id", "message"}}
Pagination fields (list endpoints only, inside meta): limit, offset,
total_count, has_more. Defaults: limit 10 (min 1, max 100), offset 0.
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

_PAGE_FIELDS = ("limit", "offset", "total_count", "has_more")


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    now = datetime.now(timezone.utc)
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": now.strftime("%Y-%m-%dT%H:%M:%S.")
        + f"{now.microsecond // 1000:03d}Z",
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, code=200, page=None):
    body = {
        "meta": _meta(page),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    resp = jsonify(body)
    resp.status_code = code
    return resp


def error_body(api_err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": api_err.error_id, "message": api_err.message},
    }
    resp = jsonify(body)
    resp.status_code = api_err.http_status
    return resp


def _parse_int_param(name, default):
    raw = request.args.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def paginate(items):
    """Slice a created_at-ASC-sorted list per the envelope pagination rules.
    Out-of-range values are clamped to the declared bounds."""
    limit = _parse_int_param("limit", 10)
    offset = _parse_int_param("offset", 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset : offset + limit]
    fields = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, fields
