"""Response envelope helpers (PRD section 2.2) and pagination (section 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

_ALNUM = string.ascii_uppercase + string.digits


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_seconds(dt):
    """ISO 8601 UTC instant with a trailing Z, second precision (fields ending _utc)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso_ms(datetime.now(timezone.utc)),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data if data is not None else {}}
    return jsonify(body), status


def list_response(rows, serializer, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = (offset + len(page)) < total
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serializer(r) for r in page],
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        raise ApiError("ERR_VALIDATION", "Query parameter '%s' must be an integer." % name)
    value = int(text)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_VALIDATION", "Query parameter '%s' may not be below %d." % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_VALIDATION", "Query parameter '%s' may not exceed %d." % (name, maximum))
    return value


def pagination():
    """PRD section 2.3 -- limit defaults to 10 (1..100), offset defaults to 0 (>= 0)."""
    limit = _int_param("limit", PAGINATION_DEFAULT_LIMIT, PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT)
    offset = _int_param("offset", PAGINATION_DEFAULT_OFFSET, 0, None)
    return limit, offset
