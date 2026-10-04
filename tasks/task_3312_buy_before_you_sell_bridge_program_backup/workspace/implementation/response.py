"""The standard response envelope (PRD 2.2) and pagination (PRD 2.3).

Success::

    {"meta": {"api_request_id": ..., "api_request_timestamp": ...},
     "response_type": "object" | "array",
     "data": {...} | [...]}

Error::

    {"meta": {"api_request_id": ..., "api_request_timestamp": ...},
     "response_type": "error",
     "data": {"error_id": ..., "message": ...}}

List responses add ``limit``, ``offset``, ``total_count`` and ``has_more`` to
``meta``.  ``limit`` defaults to 10, must be at least 1 and at most 100;
``offset`` defaults to 0.  Unless a workflow states otherwise, list results are
ordered by creation timestamp ascending, so the oldest record appears first.
"""

import random
import string

from errors import ERR_INVALID_REQUEST, ApiError
from timeutil import format_iso, now_utc

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0

_ALPHANUM = string.ascii_uppercase + string.digits


def new_request_id():
    """A server-generated request identifier starting with ``req_``."""
    suffix = "".join(random.choice(_ALPHANUM) for _ in range(18))
    return "req_" + suffix


def _meta(request_id=None, timestamp=None):
    return {
        "api_request_id": request_id or new_request_id(),
        "api_request_timestamp": format_iso(timestamp or now_utc()),
    }


def success_object(data):
    return {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }


def success_array(items, limit, offset, total_count):
    """A paginated array response.  ``items`` is already the current page."""
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }


def error_response(error):
    status = error.http_status
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": error.to_payload(),
    }
    return body, status


def parse_pagination(params):
    """Read ``limit``/``offset`` from query parameters, enforcing the bounds."""
    limit_raw = params.get("limit")
    offset_raw = params.get("offset")

    limit = PAGINATION_LIMIT_DEFAULT
    if limit_raw is not None and limit_raw != "":
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer.")
        if limit < PAGINATION_LIMIT_MIN or limit > PAGINATION_LIMIT_MAX:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "limit must be between %d and %d." % (PAGINATION_LIMIT_MIN, PAGINATION_LIMIT_MAX),
            )

    offset = PAGINATION_OFFSET_DEFAULT
    if offset_raw is not None and offset_raw != "":
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer.")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, "offset must not be negative.")

    return limit, offset


def paginate(records, limit, offset):
    """Return (page, total_count) for records already in canonical order."""
    total_count = len(records)
    return records[offset:offset + limit], total_count