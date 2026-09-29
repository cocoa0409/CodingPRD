"""The response envelope of PRD section 2.2."""

import json
import random
import string
from datetime import datetime
from decimal import Decimal

from flask import Response

import clock
import db

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def _default(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, datetime):
        return clock.fmt(obj)
    raise TypeError("not JSON serialisable: %r" % (obj,))


def _meta(extra=None):
    meta = {
        "api_request_id": request_id(),
        "api_request_timestamp": clock.fmt(clock.wall_now()),
    }
    if extra:
        meta.update(extra)
    return meta


def _emit(payload, status):
    body = json.dumps(payload, default=_default)
    return Response(body, status=status, mimetype="application/json")


def object_response(data, status=200):
    return _emit({"meta": _meta(), "response_type": "object", "data": data}, status)


def list_response(items, limit, offset, total_count):
    meta = _meta(
        {
            "limit": limit,
            "offset": offset,
            "total_count": total_count,
            "has_more": (offset + len(items)) < total_count,
        }
    )
    return _emit({"meta": meta, "response_type": "array", "data": items}, 200)


def error_response(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return _emit(payload, status)


def one(row, serializer, status=200):
    """Commit pending version bumps, then serialise a single row."""
    db.commit()
    return object_response(serializer(row), status)


def many(rows, serializer, limit, offset, total_count):
    db.commit()
    return list_response([serializer(r) for r in rows], limit, offset, total_count)


def empty(status=200):
    db.commit()
    return object_response({}, status)


def paginate(rows, limit, offset):
    total_count = len(rows)
    return rows[offset:offset + limit], total_count
