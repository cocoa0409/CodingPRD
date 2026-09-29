"""Response envelope helpers (PRD 2.2) and record serialisation."""
from decimal import Decimal

from flask import jsonify

import db


def _meta():
    return {
        "api_request_id": db.request_id(),
        "api_request_timestamp": db.now_millis(),
    }


def _plain(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value


def serialize(record):
    return {k: _plain(v) for k, v in record.items() if not k.startswith("_")}


def object_response(record, status=200):
    payload = {
        "meta": _meta(),
        "response_type": "object",
        "data": serialize(record) if record is not None else {},
    }
    return jsonify(payload), status


def empty_response(status=200):
    payload = {"meta": _meta(), "response_type": "object", "data": {}}
    return jsonify(payload), status


def list_response(records, limit, offset):
    total = len(records)
    window = records[offset: offset + limit]
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total
    meta["has_more"] = offset + len(window) < total
    payload = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in window],
    }
    return jsonify(payload), 200


def error_response(error_id, message, status):
    payload = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(payload), status
