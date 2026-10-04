"""The response envelope helpers (PRD §2.2)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALPHANUM = string.ascii_letters + string.digits


def new_request_id():
    """`req_` followed by a random alphanumeric suffix."""
    return "req_" + "".join(random.choices(_ALPHANUM, k=20))


def now_iso_millis():
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-09-01T00:00:00.000Z."""
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=(datetime.now(timezone.utc).microsecond // 1000) * 1000)
        .strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]
        + "Z"
    )


def _meta(pagination=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_iso_millis(),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def ok_object(data):
    """A 2xx response carrying a single resource."""
    return jsonify({"meta": _meta(), "response_type": "object", "data": data})


def ok_array(items, total_count, limit, offset):
    """A 2xx response carrying a page of resources plus the pagination quartet."""
    has_more = (offset + len(items)) < total_count
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": has_more,
    }
    return jsonify({"meta": _meta(pagination), "response_type": "array", "data": items})


def ok_empty():
    """A 2xx response with no payload."""
    return jsonify({"meta": _meta(), "response_type": "object", "data": {}})


def error_response(error_id, message):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        None,
    )