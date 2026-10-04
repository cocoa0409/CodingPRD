"""Response envelope helpers (PRD 2.2 / 2.3, scaffold `response_envelope`)."""

import uuid
from datetime import datetime
from decimal import Decimal

from flask import jsonify, request

import timeutil

PAGINATION_LIMIT_DEFAULT = 10
PAGINATION_LIMIT_MIN = 1
PAGINATION_LIMIT_MAX = 100
PAGINATION_OFFSET_DEFAULT = 0


def jsonable(value):
    """Strip internal keys and render datetimes / decimals for JSON."""
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, datetime):
        return timeutil.iso(value)
    if isinstance(value, Decimal):
        return float(value)
    return value


def _meta(extra=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:16].upper(),
        "api_request_timestamp": timeutil.iso(timeutil.now()),
    }
    if extra:
        meta.update(extra)
    return meta


def success(data, status=200, response_type="object", meta_extra=None):
    body = {
        "meta": _meta(meta_extra),
        "response_type": response_type,
        "data": jsonable(data),
    }
    return jsonify(body), status


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def error_response(error_id, message, status):
    return jsonify(error_body(error_id, message)), status


def _int_arg(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def paginate(items, key=None):
    """Slice a list and build the list-response meta block.

    `limit` defaults to 10 and is clamped into [1, 100]; `offset` defaults to 0.
    """
    limit = _int_arg("limit", PAGINATION_LIMIT_DEFAULT)
    if limit < PAGINATION_LIMIT_MIN:
        limit = PAGINATION_LIMIT_MIN
    if limit > PAGINATION_LIMIT_MAX:
        limit = PAGINATION_LIMIT_MAX
    offset = _int_arg("offset", PAGINATION_OFFSET_DEFAULT)
    if offset < 0:
        offset = 0

    rows = list(items)
    if key is not None:
        rows.sort(key=key)
    total = len(rows)
    page = rows[offset:offset + limit]
    meta_extra = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta_extra


def list_response(items, key=None):
    page, meta_extra = paginate(items, key=key)
    return success(page, status=200, response_type="array", meta_extra=meta_extra)


def by_created_at(row):
    return (row["created_at"], row["_seq"])
