"""Standard response envelope (PRD 2.2) and JSON coercion."""

from datetime import datetime, timezone
from decimal import Decimal

from flask import jsonify

import store


def _meta():
    return {
        "api_request_id": store.new_request_id(),
        "api_request_timestamp": store.fmt_dt(datetime.now(timezone.utc)),
    }


def jsonable(value):
    if isinstance(value, Decimal):
        text = format(value, "f")
        if "." in text:
            return float(text)
        return int(text)
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if isinstance(value, datetime):
        return store.fmt_dt(value)
    return value


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": jsonable(data if data is not None else {}),
    }
    return jsonify(body), status


def list_response(rows, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": jsonable(list(rows)),
    }
    return jsonify(body), 200


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
