"""Standard response envelope helpers per scaffold §1.0 / PRD §2.2."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError


def _new_request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + datetime.now(
        timezone.utc
    ).strftime("%f")[:3] + "Z"


def _meta():
    return {
        "api_request_id": _new_request_id(),
        "api_request_timestamp": _now_iso(),
    }


def _scrub(value):
    """Strip server-internal fields (underscore-prefixed keys) from entities."""
    if isinstance(value, dict):
        return {k: _scrub(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    return value


def ok(data, status=200, pagination=None):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": _scrub(data),
    }
    if pagination is not None:
        body["meta"]["limit"] = pagination["limit"]
        body["meta"]["offset"] = pagination["offset"]
        body["meta"]["total_count"] = pagination["total_count"]
        body["meta"]["has_more"] = pagination["has_more"]
    return jsonify(body), status


def _parse_pagination_int(raw):
    """Strictly parse an integer pagination value; None if malformed."""
    try:
        return int(raw)
    except (TypeError, ValueError):
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return None


def paginate(items):
    """Slice a list by limit/offset query params; return (slice, pagination_meta).

    Malformed limit/offset or out-of-range values (limit < 1 or > 100,
    offset < 0) are rejected with ERR_VALIDATION (HTTP 422). Hitting the
    max on limit is client error per §2.3 ("maximum of 100"), not silent
    clamping.
    """
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10 if raw_limit is None else _parse_pagination_int(raw_limit)
    offset = 0 if raw_offset is None else _parse_pagination_int(raw_offset)
    if limit is None or limit < 1 or limit > 100:
        raise ApiError(
            "ERR_VALIDATION", "limit must be an integer between 1 and 100", 422
        )
    if offset is None or offset < 0:
        raise ApiError(
            "ERR_VALIDATION", "offset must be a non-negative integer", 422
        )
    total_count = len(items)
    page = items[offset : offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + limit) < total_count,
    }
    return page, pagination
