"""Response envelope (PRD 2.2) and entity serialization."""
import secrets
from datetime import datetime
from decimal import Decimal

from flask import jsonify, request

import db
import timeutil
from constants import PAGE_DEFAULT_LIMIT, PAGE_DEFAULT_OFFSET, PAGE_MAX_LIMIT, PAGE_MIN_LIMIT
from errors import ApiError, ERR_INVALID_REQUEST


def _request_id():
    return "req_" + secrets.token_hex(12)


def _meta(extra=None):
    meta = {
        "api_request_id": _request_id(),
        "api_request_timestamp": timeutil.wall_now_iso(),
    }
    if extra:
        meta.update(extra)
    return meta


def serialize(value):
    """Convert an entity (or nested structure) to JSON-safe form.

    Strips internal keys (leading underscore), converts datetimes to the
    3-fractional-digit UTC format and Decimals to floats.
    """
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [serialize(v) for v in value]
    if isinstance(value, datetime):
        return timeutil.iso3(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


def respond_object(entity, code=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": serialize(entity),
    }
    return jsonify(body), code


def parse_pagination():
    """Read limit/offset query params with PRD 2.3 defaults and bounds."""
    args = request.args
    limit = PAGE_DEFAULT_LIMIT
    offset = PAGE_DEFAULT_OFFSET
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if isinstance(limit, bool) or limit < PAGE_MIN_LIMIT or limit > PAGE_MAX_LIMIT:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit out of range")
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


def respond_list(entities, code=200):
    limit, offset = parse_pagination()
    total = len(entities)
    page = entities[offset:offset + limit]
    meta = _meta({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    })
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(e) for e in page],
    }
    return jsonify(body), code


def respond_error(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
