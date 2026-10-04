"""Shared helpers for route modules."""

from __future__ import annotations

from errors import ApiError, E_INVALID_REQUEST
import response as resp


DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0


def page_params(request):
    limit_raw = request.query.get("limit")
    offset_raw = request.query.get("offset")
    if limit_raw is None or limit_raw == "":
        limit = DEFAULT_LIMIT
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError(E_INVALID_REQUEST, "limit must be an integer")
    if offset_raw is None or offset_raw == "":
        offset = DEFAULT_OFFSET
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError(E_INVALID_REQUEST, "offset must be an integer")
    if limit < MIN_LIMIT:
        limit = MIN_LIMIT
    if limit > MAX_LIMIT:
        limit = MAX_LIMIT
    if offset < 0:
        offset = 0
    return limit, offset


def paginate(records, limit, offset):
    total = len(records)
    return records[offset:offset + limit], total


def paged_response(records, limit, offset):
    page, total = paginate(records, limit, offset)
    return resp.paged(page, limit, offset, total)


def q(request, name, default=None):
    value = request.query.get(name)
    if value is None or value == "":
        return default
    return value


def q_bool(request, name):
    value = q(request, name)
    if value is None:
        return None
    return str(value).lower() in ("1", "true", "yes")


def q_int(request, name):
    value = q(request, name)
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError(E_INVALID_REQUEST, "%s must be an integer" % name)