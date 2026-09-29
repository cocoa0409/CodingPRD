"""Standard response envelope helpers (PRD 2.2, 2.3)."""
import json
import uuid
from decimal import Decimal

from flask import Response

import db as store

LIMIT_DEFAULT = 10
LIMIT_MIN = 1
LIMIT_MAX = 100
OFFSET_DEFAULT = 0


def _default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(repr(obj) + " is not JSON serialisable")


def _meta(extra=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex,
        "api_request_timestamp": store.iso(store.db.now),
    }
    if extra:
        meta.update(extra)
    return meta


def _emit(body, status):
    payload = json.dumps(body, default=_default)
    return Response(payload, status=status, mimetype="application/json")


def ok(data=None, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data if data is not None else {},
    }
    return _emit(body, status)


def created(data):
    return ok(data, 201)


def collection(rows, limit, offset):
    total = len(rows)
    page = rows[offset:offset + limit]
    body = {
        "meta": _meta({
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": (offset + len(page)) < total,
        }),
        "response_type": "array",
        "data": page,
    }
    return _emit(body, 200)


def error(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _emit(body, status)
