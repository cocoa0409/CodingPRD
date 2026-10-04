"""Standard response envelope (SCAFFOLD 1.0 / PRD 2.2).

Success:
  { "meta": {api_request_id, api_request_timestamp, [pagination...]},
    "response_type": "object" | "array", "data": {...} }
Error:
  { "meta": {api_request_id, api_request_timestamp},
    "response_type": "error", "data": {error_id, message} }
"""

import random
import string
from datetime import datetime, timezone

_ALPHANUM = string.ascii_uppercase + string.digits


def _request_id():
    body = "".join(random.choice(_ALPHANUM) for _ in range(18))
    return "req_" + body


def _timestamp():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _timestamp(),
    }
    if extra:
        meta.update(extra)
    return meta


def object_body(data, status=200, meta_extra=None):
    return ({"meta": _meta(meta_extra), "response_type": "object", "data": data}, status)


def array_body(items, limit, offset, total_count):
    has_more = (offset + len(items)) < total_count
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return (
        {"meta": _meta(meta_extra), "response_type": "array", "data": items},
        200,
    )


def error_body(error_id, message, status):
    return (
        {
            "meta": _meta(),
            "response_type": "error",
            "data": {"error_id": error_id, "message": message},
        },
        status,
    )


def paginate(records, limit, offset):
    """Return (page_items, limit, offset, total_count) for a list response."""
    total = len(records)
    page = records[offset:offset + limit]
    return page, limit, offset, total