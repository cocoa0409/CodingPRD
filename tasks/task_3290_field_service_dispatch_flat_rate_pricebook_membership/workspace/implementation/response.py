"""Response envelope helpers (PRD 2.2, 2.3)."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

from constants import (RESPONSE_ARRAY, RESPONSE_ERROR, RESPONSE_OBJECT,
                       DEFAULT_LIMIT, MAX_LIMIT, MIN_LIMIT, DEFAULT_OFFSET)
from errors import ApiError, ERR_INVALID_REQUEST

_ALPHABET = string.ascii_uppercase + string.digits


def request_id():
    body = "".join(random.choice(_ALPHABET) for _ in range(18))
    return "req_" + body


def _stamp():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def meta(extra=None):
    base = {"api_request_id": request_id(), "api_request_timestamp": _stamp()}
    if extra:
        base.update(extra)
    return base


def success(data, response_type=RESPONSE_OBJECT, status=200, page=None):
    body = {"meta": meta(page), "response_type": response_type, "data": data}
    return jsonify(body), status


def created(data):
    return success(data, RESPONSE_OBJECT, 201)


def object_ok(data):
    return success(data, RESPONSE_OBJECT, 200)


def array_ok(items, limit, offset, total_count):
    page = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + limit) < total_count,
    }
    return success(items, RESPONSE_ARRAY, 200, page=page)


def error_body(err):
    if isinstance(err, ApiError):
        error_id = err.error_id
        message = err.message
        status = err.http_status
    else:
        error_id = ERR_INVALID_REQUEST
        message = str(err) or ERR_INVALID_REQUEST
        status = 400
    body = {
        "meta": meta(),
        "response_type": RESPONSE_ERROR,
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


def read_pagination(args):
    """limit defaults to 10, range 1..100; offset defaults to 0 (PRD 2.3)."""
    limit_raw = args.get("limit")
    offset_raw = args.get("offset")
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET
    if limit_raw not in (None, ""):
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "limit must be an integer")
    if offset_raw not in (None, ""):
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, "offset must be an integer")
    if limit < MIN_LIMIT or limit > MAX_LIMIT:
        raise ApiError(ERR_INVALID_REQUEST,
                       "limit must be between %d and %d" % (MIN_LIMIT, MAX_LIMIT))
    if offset < 0:
        raise ApiError(ERR_INVALID_REQUEST, "offset must not be negative")
    return limit, offset


def paginate(items, limit, offset):
    total = len(items)
    return items[offset:offset + limit], total