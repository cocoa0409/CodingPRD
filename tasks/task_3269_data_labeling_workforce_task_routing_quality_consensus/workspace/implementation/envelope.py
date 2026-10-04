"""Response envelope helpers (PRD section 2.2).

Success:
    {"meta": {"api_request_id", "api_request_timestamp", ...pagination},
     "response_type": "object" | "array",
     "data": {...} | [...]}

Error:
    {"meta": {"api_request_id", "api_request_timestamp"},
     "response_type": "error",
     "data": {"error_id", "message"}}
"""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

_ALPHANUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(18))


def request_timestamp():
    """ISO 8601 UTC with three fractional digits."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": request_timestamp(),
    }


def ok(data, status=200, pagination=None):
    meta = _meta()
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    return jsonify({"meta": meta, "response_type": "object", "data": data}), status


def list_ok(rows, status=200, pagination=None):
    meta = _meta()
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    return jsonify({"meta": meta, "response_type": "array", "data": rows}), status


def error_response(error_id, message, status):
    return (
        jsonify(
            {
                "meta": _meta(),
                "response_type": "error",
                "data": {"error_id": error_id, "message": message},
            }
        ),
        status,
    )


def paginate(rows, limit, offset):
    """Apply the pagination contract of PRD section 2.3 to an ordered list."""
    total_count = len(rows)
    page = rows[offset : offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": offset + limit < total_count,
    }