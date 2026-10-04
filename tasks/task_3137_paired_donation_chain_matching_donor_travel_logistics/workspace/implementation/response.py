"""Response envelope helpers per PRD §2.2."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def _meta_ts():
    """Server wall-clock timestamp with millisecond precision."""
    return (
        datetime.now(timezone.utc)
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )


def success_response(data, status=200, pagination=None):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _meta_ts(),
        },
        "response_type": "array" if pagination is not None else "object",
        "data": data,
    }
    if pagination is not None:
        body["meta"].update(
            {
                "limit": pagination["limit"],
                "offset": pagination["offset"],
                "total_count": pagination["total_count"],
                "has_more": pagination["has_more"],
            }
        )
    return jsonify(body), status


def error_response(error_id, message, http_status):
    body = {
        "meta": {
            "api_request_id": _request_id(),
            "api_request_timestamp": _meta_ts(),
        },
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
