"""Standard response envelope helpers (PRD 2.2 / 2.3)."""

import random
import string

from flask import jsonify, request

from errors import ApiError
from store import iso3, store

_ALPHANUM = string.ascii_uppercase + string.digits

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso3(store.now()),
    }


def object_response(data, status=200):
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def array_response(rows, limit, offset, total_count, status=200):
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": rows,
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _base_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status


# ---------------------------------------------------------------------------
# pagination
# ---------------------------------------------------------------------------

def _parse_pagination_int(raw, field):
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % field)
    negative = text.startswith("-")
    digits = text[1:] if negative else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer." % field)
    value = int(text)
    return value


def pagination_params():
    """Read and validate limit/offset from the query string (PRD 2.3)."""
    limit = _parse_pagination_int(request.args.get("limit"), "limit")
    offset = _parse_pagination_int(request.args.get("offset"), "offset")
    if limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    elif limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "limit must be between %d and %d." % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT),
        )
    if offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    elif offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "offset may not be negative.")
    return limit, offset


def paginated(rows, serializer):
    limit, offset = pagination_params()
    total = len(rows)
    page = rows[offset:offset + limit]
    return array_response([serializer(row) for row in page], limit, offset, total)
