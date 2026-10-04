"""Response envelope helpers, matching SCAFFOLD response_envelope exactly:
success: {meta: {api_request_id, api_request_timestamp, [limit, offset,
total_count, has_more]}, response_type: "object"|"array", data: ...}
error:   {meta: {api_request_id, api_request_timestamp},
          response_type: "error", data: {error_id, message}}
"""
import secrets
import string
from datetime import datetime, timezone

from flask import jsonify

from util_time import iso_ms

_ALPHANUM = string.ascii_letters + string.digits


def _request_id():
    return "req_" + "".join(secrets.choice(_ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_ms(datetime.now(timezone.utc)),
    }


def ok(data, status=200, pagination=None):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    if pagination is not None:
        body["meta"].update(pagination)
    return jsonify(body), status


def error_response(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def page_payload(items, limit, offset):
    """Slice a pre-sorted list and build the pagination meta fields."""
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, meta
