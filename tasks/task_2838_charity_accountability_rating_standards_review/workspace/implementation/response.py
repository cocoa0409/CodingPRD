"""Response envelope helpers (PRD section 2.2 / 2.3)."""

import random
import string
from datetime import datetime
from decimal import Decimal

from flask import jsonify

from db import fmt_dt, store

_ALPHABET = string.ascii_lowercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALPHABET) for _ in range(24))


def sanitize(value):
    """Render Decimals as JSON numbers and datetimes in the declared format."""
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return fmt_dt(value)
    if isinstance(value, dict):
        return {k: sanitize(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, (list, tuple)):
        return [sanitize(v) for v in value]
    return value


def _meta(pagination=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": fmt_dt(store.now()),
    }
    if pagination:
        meta.update(pagination)
    return meta


def ok(data=None, status=200, pagination=None, response_type="object"):
    body = {
        "meta": _meta(pagination),
        "response_type": response_type,
        "data": sanitize({} if data is None else data),
    }
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + len(items)) < total_count,
    }
    return ok(items, 200, pagination=pagination, response_type="array")


def ok_object_paginated(data, limit, offset, total_count, window_len):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
        "has_more": (offset + window_len) < total_count,
    }
    return ok(data, 200, pagination=pagination, response_type="object")


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def paginate(items, limit, offset):
    """Sort has already been applied; window it."""
    return items[offset: offset + limit]
