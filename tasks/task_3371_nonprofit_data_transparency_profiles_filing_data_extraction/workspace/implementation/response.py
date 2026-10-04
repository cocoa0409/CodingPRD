"""The standard response envelope (PRD 2.2, SCAFFOLD 1.0).

Success:
  { "meta": {api_request_id, api_request_timestamp, [limit, offset,
             total_count, has_more]}, "response_type": "object"|"array",
    "data": ... }
Error:
  { "meta": {api_request_id, api_request_timestamp}, "response_type": "error",
    "data": {"error_id": ..., "message": ...} }
"""

import random
import string

import clock

_ALPHABET = string.ascii_letters + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(20))


def meta(extra=None):
    payload = {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.fmt_dt(clock.now()),
    }
    if extra:
        payload.update(extra)
    return payload


def ok(data, status=200, pagination=None):
    if isinstance(data, list):
        response_type = "array"
    else:
        response_type = "object"
    return {
        "meta": meta(pagination),
        "response_type": response_type,
        "data": data,
    }, status


def ok_list(items, total_count, limit, offset, status=200):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return {
        "meta": meta(pagination),
        "response_type": "array",
        "data": items,
    }, status


def error(error_id, message, status):
    return {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }, status


# --- pagination parameters (PRD 2.3 / SCAFFOLD 1.0) ---------------------

DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def read_pagination(args):
    """Read limit/offset query parameters, applying the declared bounds."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET
    if limit_raw is not None and str(limit_raw) != "":
        try:
            limit = int(str(limit_raw))
        except ValueError:
            limit = DEFAULT_LIMIT
        if limit < MIN_LIMIT:
            limit = MIN_LIMIT
        if limit > MAX_LIMIT:
            limit = MAX_LIMIT
    if offset_raw is not None and str(offset_raw) != "":
        try:
            offset = int(str(offset_raw))
        except ValueError:
            offset = DEFAULT_OFFSET
        if offset < 0:
            offset = DEFAULT_OFFSET
    return limit, offset
