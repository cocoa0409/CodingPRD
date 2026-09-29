"""Uniform response envelope and pagination (PRD 2.2)."""

import random
import string

from flask import jsonify, request

from constants import (
    LIMIT_DEFAULT,
    LIMIT_MAX,
    LIMIT_MIN,
    OFFSET_DEFAULT,
    OFFSET_MIN,
)
from errors import bad_request
from store import store
from timeutil import iso

ALNUM = string.ascii_letters + string.digits


def request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": iso(store.now()),
    }


def envelope(data, response_type, extra_meta=None):
    meta = base_meta()
    if extra_meta:
        meta.update(extra_meta)
    return {"meta": meta, "response_type": response_type, "data": data}


def ok(data=None, status=200):
    """A single-object (or empty) success response."""
    return jsonify(envelope({} if data is None else data, "object")), status


def created(data):
    return ok(data, 201)


def error_response(error_id, message):
    body = envelope({"error_id": error_id, "message": message}, "error")
    return body


def pagination_args():
    """Read and validate limit/offset (PRD 2.2)."""
    limit = LIMIT_DEFAULT
    offset = OFFSET_DEFAULT
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise bad_request("limit must be an integer")
        if limit < LIMIT_MIN or limit > LIMIT_MAX:
            raise bad_request("limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise bad_request("offset must be an integer")
        if offset < OFFSET_MIN:
            raise bad_request("offset must be zero or greater")
    return limit, offset


def paginated(records, serializer):
    """Window a fully filtered, fully sorted list into a list response."""
    limit, offset = pagination_args()
    total = len(records)
    window = records[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(window) < total,
    }
    data = [serializer(rec) for rec in window]
    return jsonify(envelope(data, "array", meta)), 200
