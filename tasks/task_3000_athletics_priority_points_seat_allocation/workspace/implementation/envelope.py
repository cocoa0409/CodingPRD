"""Standard success / error response envelopes (PRD section 2.2, 2.3)."""
import random
import string

from flask import jsonify, request

import clock
from errors import invalid

_ALNUM = string.ascii_uppercase + string.digits

PAGE_LIMIT_DEFAULT = 10
PAGE_LIMIT_MIN = 1
PAGE_LIMIT_MAX = 100
PAGE_OFFSET_DEFAULT = 0


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.iso3(clock.now()),
    }


def ok(data, status=200):
    """A single-resource (or inline computed) success response."""
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, total_count, limit, offset):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(api_error):
    return jsonify(error_body(api_error.error_id, api_error.message)), api_error.http_status


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------
def _int_param(name, default, minimum, maximum):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        raise invalid("'%s' must be an integer" % name)
    if minimum is not None and value < minimum:
        raise invalid("'%s' must be at least %d" % (name, minimum))
    if maximum is not None and value > maximum:
        raise invalid("'%s' must not exceed %d" % (name, maximum))
    return value


def pagination():
    """Read and validate limit / offset from the query string."""
    limit = _int_param("limit", PAGE_LIMIT_DEFAULT, PAGE_LIMIT_MIN, PAGE_LIMIT_MAX)
    offset = _int_param("offset", PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def paginated(rows, serializer):
    """Apply limit/offset to an already-ordered, already-filtered row list."""
    limit, offset = pagination()
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([serializer(row) for row in page], total, limit, offset)
