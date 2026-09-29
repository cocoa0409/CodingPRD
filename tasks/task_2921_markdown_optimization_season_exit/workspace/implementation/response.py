"""Response envelope helpers (PRD 2.2 / 2.3)."""

import json

from flask import Response, request

from common import new_request_id, now_instant
from errors import ApiError

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _meta(extra=None):
    meta = {
        "api_request_id": new_request_id(),
        "api_request_timestamp": now_instant(),
    }
    if extra:
        meta.update(extra)
    return meta


def _envelope(body, status):
    payload = json.dumps(body, allow_nan=False)
    return Response(payload, status=status, mimetype="application/json")


def ok(data=None, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return _envelope(body, status)


def created(data):
    return ok(data, 201)


def ok_array(rows, status=200):
    body = {
        "meta": _meta(),
        "response_type": "array",
        "data": rows,
    }
    return _envelope(body, status)


def ok_list(rows, limit, offset, status=200):
    total = len(rows)
    page = rows[offset:offset + limit]
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + len(page)) < total,
        }),
        "response_type": "array",
        "data": page,
    }
    return _envelope(body, status)


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return _envelope(body, err.http_status)


# --------------------------------------------------------------------------
# Query parameters
# --------------------------------------------------------------------------

def _int_arg(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None:
        return default
    text = raw.strip()
    if text == "" or not (text.isdigit() or
                          (text.startswith("-") and text[1:].isdigit())):
        raise ApiError("ERR_VALIDATION",
                       "Query parameter '%s' must be an integer." % name)
    value = int(text)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_VALIDATION",
                       "Query parameter '%s' is below the permitted minimum."
                       % name)
    if maximum is not None and value > maximum:
        raise ApiError("ERR_VALIDATION",
                       "Query parameter '%s' exceeds the permitted maximum."
                       % name)
    return value


def pagination():
    """limit defaults to 10 (1..100); offset defaults to 0 and is never clamped."""
    limit = _int_arg("limit", PAGINATION_DEFAULT_LIMIT,
                     PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
    offset = _int_arg("offset", PAGINATION_DEFAULT_OFFSET, 0, None)
    return limit, offset


def filter_str(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw


def filter_enum(name, allowed):
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        raise ApiError("ERR_VALIDATION",
                       "Filter '%s' is not a member of its enumeration." % name)
    return raw


def filter_date(name):
    from common import parse_date
    raw = request.args.get(name)
    if raw is None:
        return None
    if parse_date(raw) is None:
        raise ApiError("ERR_VALIDATION",
                       "Filter '%s' must be an ISO date (YYYY-MM-DD)." % name)
    return raw
