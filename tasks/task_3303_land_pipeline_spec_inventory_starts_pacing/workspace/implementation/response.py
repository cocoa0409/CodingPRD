"""Response envelope helpers per PRD section 2.2 / 2.3."""

import random
import string

from flask import jsonify, request

from db import now_wall, iso3
from errors import ApiError


def _request_id():
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=20))
    return "req_" + suffix


def _meta(pagination=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": iso3(now_wall()),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def _parse_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", 400, "offset must be >= 0")
    return limit, offset


def success_obj(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, status=200):
    limit, offset = _parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }
    body = {"meta": _meta(pagination), "response_type": "array", "data": page}
    return jsonify(body), status


def error_response(e):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status
