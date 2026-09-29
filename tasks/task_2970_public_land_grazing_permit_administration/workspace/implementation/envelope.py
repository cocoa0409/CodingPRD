"""Response envelope helpers (PRD section 2.2) and pagination (PRD section 2.3)."""

import random
import string

from flask import jsonify, request

from errors import ApiError
from store import wall_now_iso

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0
OFFSET_MIN = 0

_ALPHABET = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(20))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": wall_now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def listing(items, limit, offset, total_count):
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": offset + len(items) < total_count,
        }),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(err):
    return jsonify(error_body(err.error_id, err.message)), err.http_status


# ------------------------------------------------------------------ pagination


def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    text = raw.strip()
    try:
        value = int(text)
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", "%s must be an integer" % name)
    if value < minimum:
        raise ApiError("ERR_VALIDATION", "%s must be at least %d" % (name, minimum))
    if maximum is not None and value > maximum:
        raise ApiError("ERR_VALIDATION", "%s must be at most %d" % (name, maximum))
    return value


def page_params():
    """Validated (limit, offset). Out-of-bounds values are a shape failure."""
    limit = _int_param("limit", LIMIT_DEFAULT, LIMIT_MIN, LIMIT_MAX)
    offset = _int_param("offset", OFFSET_DEFAULT, OFFSET_MIN, None)
    return limit, offset


def paginate(records, serializer):
    limit, offset = page_params()
    total = len(records)
    window = records[offset:offset + limit]
    return listing([serializer(record) for record in window], limit, offset, total)


def sort_default(records):
    """Default list order: created_at ascending, oldest first."""
    return sorted(records, key=lambda record: (record["created_at"], record["_seq"]))
