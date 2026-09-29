"""The response envelope of PRD 2.2 and the offset pagination of PRD 2.3."""

import datetime
import random
import string

from flask import jsonify

from errors import ApiError
from util import UTC, format_instant

ALPHANUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(ALPHANUM) for _ in range(20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": format_instant(datetime.datetime.now(UTC)),
    }


def object_response(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data or {}}
    return jsonify(body), status


def created(data):
    return object_response(data, 201)


def list_response(rows, serializer, limit, offset):
    """A paginated array response: total_count counts the filtered set."""
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
        "data": [serializer(row) for row in page],
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def api_error_response(err):
    return error_response(err.error_id, err.message, err.http_status)


def pagination(args):
    """limit defaults to 10 (1..100), offset defaults to 0 (>= 0); out of range
    values are a schema violation rather than being silently clamped."""
    limit = PAGINATION_DEFAULT_LIMIT
    offset = PAGINATION_DEFAULT_OFFSET
    raw_limit = args.get("limit")
    if raw_limit is not None:
        limit = _positive_int(raw_limit, "limit")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            raise ApiError("ERR_VALIDATION", "limit must be between 1 and 100.")
    raw_offset = args.get("offset")
    if raw_offset is not None:
        offset = _positive_int(raw_offset, "offset")
        if offset < 0:
            raise ApiError("ERR_VALIDATION", "offset must be at least 0.")
    return limit, offset


def _positive_int(raw, name):
    text = str(raw).strip()
    try:
        if text != str(int(text)):
            raise ValueError
        return int(text)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "%s must be an integer." % name)
