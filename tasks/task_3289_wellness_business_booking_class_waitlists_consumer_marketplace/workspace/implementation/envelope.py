"""Response envelope construction and pagination helpers.

Envelope (read verbatim from SCAFFOLD §1.0 / PRD §2.2):

  success: {"meta": {"api_request_id", "api_request_timestamp", ...},
            "response_type": "object" | "array", "data": {...}}
  error:   {"meta": {"api_request_id", "api_request_timestamp"},
            "response_type": "error",
            "data": {"error_id": ..., "message": ...}}

Pagination meta fields are limit / offset / total_count / has_more with
defaults limit=10, min=1, max=100, offset=0 (SCAFFOLD §1.0).
"""

import random
import string

from core import ApiError, ERROR_HTTP, fmt, now

ALPHANUM = string.ascii_letters + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(18))


def _meta_base():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt(now()),
    }


def ok(data, status=200):
    """Object-shaped success envelope."""
    body = {"meta": _meta_base(), "response_type": "object", "data": data}
    return body, status


def empty(status=200):
    return ok({}, status)


def error_body(error_id, message):
    return {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def read_pagination(args):
    """Pull limit / offset off the request arguments with the declared rules."""
    raw_limit = args.get("limit")
    if raw_limit in (None, ""):
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer", 400)
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError(
                "ERR_INVALID_PAGINATION",
                "limit must be between %d and %d"
                % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT),
                400,
            )

    raw_offset = args.get("offset")
    if raw_offset in (None, ""):
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer", 400)
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be >= 0", 400)
    return limit, offset


def paged(items, limit, offset):
    """Return (page, meta_pagination) for an already-ordered list."""
    total = len(items)
    page = items[offset: offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }


def array_response(items, limit, offset, extra_meta=None):
    page, meta = paged(items, limit, offset)
    result = {"meta": _meta_base(), "response_type": "array", "data": page}
    result["meta"].update(meta)
    if extra_meta:
        result["meta"].update(extra_meta)
    return result, 200


def object_response(data, extra_meta=None, status=200):
    result = {"meta": _meta_base(), "response_type": "object", "data": data}
    if extra_meta:
        result["meta"].update(extra_meta)
    return result, status


def error_status(error_id):
    return ERROR_HTTP.get(error_id, 400)