"""Response envelope builders and pagination parsing (PRD sections 2.2-2.3).

Success:  {"meta": {...}, "response_type": "object"|"array", "data": ...}
Error:    {"meta": {...}, "response_type": "error",
           "data": {"error_id": ..., "message": ...}}
List meta additionally carries limit/offset/total_count/has_more.
"""

import random
import string

from flask import jsonify

import clock
from constants import (
    PAGE_DEFAULT_LIMIT,
    PAGE_DEFAULT_OFFSET,
    PAGE_MAX_LIMIT,
    PAGE_MIN_LIMIT,
)
from errors import api_error


def make_meta(extra=None):
    meta = {
        "api_request_id": "req_"
        + "".join(random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": clock.wall_now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def ok_object(data, status=200):
    body = {"meta": make_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = make_meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        }
    )
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), 200


def error_response(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_pagination(args):
    """Validate limit/offset query parameters per section 2.3."""
    limit = PAGE_DEFAULT_LIMIT
    offset = PAGE_DEFAULT_OFFSET
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit), 10)
        except (TypeError, ValueError):
            raise api_error(
                "ERR_INVALID_PAGINATION_PARAMETERS",
                "limit must be an integer between %d and %d"
                % (PAGE_MIN_LIMIT, PAGE_MAX_LIMIT),
            )
        if limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
            raise api_error(
                "ERR_INVALID_PAGINATION_PARAMETERS",
                "limit must be between %d and %d" % (PAGE_MIN_LIMIT, PAGE_MAX_LIMIT),
            )
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset), 10)
        except (TypeError, ValueError):
            raise api_error(
                "ERR_INVALID_PAGINATION_PARAMETERS",
                "offset must be a non-negative integer",
            )
        if offset < 0:
            raise api_error(
                "ERR_INVALID_PAGINATION_PARAMETERS", "offset must be non-negative"
            )
    return limit, offset


def paginate(items, limit, offset):
    return items[offset : offset + limit]
