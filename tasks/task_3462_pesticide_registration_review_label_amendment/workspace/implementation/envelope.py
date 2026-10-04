"""Response envelope helpers (PRD 2.2) plus serialization of stored rows."""
import uuid
from datetime import datetime
from decimal import Decimal

from flask import jsonify

import clock
from db import iso3, wall_iso


def _request_id():
    return "req_" + uuid.uuid4().hex[:20]


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": wall_iso(),
    }


def serialize(value):
    """Deep-convert stored rows to JSON-safe structures.

    datetime -> canonical logical-clock string; Decimal -> float; rows keep
    insertion order; internal keys (leading underscore) are dropped.
    """
    if isinstance(value, datetime):
        return clock.iso_z(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: serialize(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [serialize(v) for v in value]
    return value


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": serialize(data)}
    return jsonify(body), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": [serialize(i) for i in items]}
    return jsonify(body), 200


def error_body(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
