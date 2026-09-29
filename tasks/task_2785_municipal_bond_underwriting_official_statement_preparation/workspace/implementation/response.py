"""Response envelope helpers (PRD 2.2, 2.3)."""
import random
import string
from datetime import timezone
from decimal import Decimal

from flask import jsonify, request

import db
from errors import ApiError

PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

_ID_ALPHABET = string.ascii_uppercase + string.digits


def iso(value):
    """ISO 8601 UTC with exactly three fractional digits, Z suffix."""
    if value is None:
        return None
    aware = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        aware.year,
        aware.month,
        aware.day,
        aware.hour,
        aware.minute,
        aware.second,
        aware.microsecond // 1000,
    )


def jsonable(value):
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "tzinfo"):
        return iso(value)
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def request_id():
    return "req_" + "".join(random.choice(_ID_ALPHABET) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(db.now()),
    }


def ok(data, code=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return jsonify(body), code


def created(data):
    return ok(data, 201)


def ok_list(items, meta_extra):
    meta = base_meta()
    meta.update(meta_extra)
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(error):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error.error_id, "message": error.message},
    }
    return jsonify(body), error.http_status


def _parse_int_param(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    raw = raw.strip()
    if raw == "":
        raise ApiError("ERR_INVALID_PAGINATION")
    negative = raw.startswith("-")
    digits = raw[1:] if negative else raw
    if not digits.isdigit():
        raise ApiError("ERR_INVALID_PAGINATION")
    value = int(raw)
    return value


def parse_pagination():
    """PRD 2.3: limit defaults to 10, min 1, max 100; offset defaults to 0, non-negative."""
    limit = _parse_int_param("limit")
    offset = _parse_int_param("offset")
    if limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    elif limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
        raise ApiError("ERR_INVALID_PAGINATION")
    if offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    elif offset < 0:
        raise ApiError("ERR_INVALID_PAGINATION")
    return limit, offset


def paginated(rows, serializer):
    limit, offset = parse_pagination()
    total = len(rows)
    window = rows[offset:offset + limit]
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    return ok_list([serializer(row) for row in window], meta_extra)
