"""Response envelope helpers (PRD 2.2 / 2.3)."""
from decimal import Decimal

from flask import jsonify

import store


def _meta():
    return {"api_request_id": store.request_id(),
            "api_request_timestamp": store.now_iso()}


def clean(value):
    """Drop private keys and render Decimals as JSON numbers."""
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [clean(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    return value


def ok(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": clean(data or {})}
    return jsonify(body), status


def created(data):
    return ok(data, 201)


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": clean(items)}
    return jsonify(body), 200


def error(error_id, message, status):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return jsonify(body), status
