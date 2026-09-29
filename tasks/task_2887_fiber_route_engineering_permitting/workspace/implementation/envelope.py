"""Response envelope helpers (PRD section 2.2 / 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError
from store import commit

_ALNUM = string.ascii_uppercase + string.digits

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0
PAGINATION_OFFSET_MIN = 0


def _request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _request_timestamp():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def _base_meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": _request_timestamp(),
    }


def object_response(data, status=200):
    """A single-resource (or empty) 2xx envelope."""
    commit()
    body = {
        "meta": _base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def list_response(items, total_count, limit, offset):
    commit()
    meta = _base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


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


# --------------------------------------------------------------------------
# pagination
# --------------------------------------------------------------------------

def _parse_int_param(raw, name):
    text = raw.strip()
    if text == "":
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    negative = text.startswith("-")
    digits = text[1:] if negative or text.startswith("+") else text
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    value = int(text)
    return value


def pagination():
    """Read and validate limit/offset per PRD section 2.3."""
    limit = PAGINATION_LIMIT_DEFAULT
    offset = PAGINATION_OFFSET_DEFAULT

    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        limit = _parse_int_param(raw_limit, "limit")
        if limit < PAGINATION_LIMIT_MIN or limit > PAGINATION_LIMIT_MAX:
            raise ApiError(
                "ERR_INVALID_REQUEST",
                "limit must be between %d and %d." % (PAGINATION_LIMIT_MIN, PAGINATION_LIMIT_MAX),
            )

    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        offset = _parse_int_param(raw_offset, "offset")
        if offset < PAGINATION_OFFSET_MIN:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be at least 0.")

    return limit, offset


def paginate(records, serializer):
    limit, offset = pagination()
    total = len(records)
    window = records[offset:offset + limit]
    return list_response([serializer(r) for r in window], total, limit, offset)


def filter_value(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    return raw


def bool_filter(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    return None
