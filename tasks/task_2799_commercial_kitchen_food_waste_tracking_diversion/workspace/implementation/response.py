"""Response envelope helpers (PRD 2.2, 2.3)."""
import random
import string

from flask import jsonify

from db import db, serialize

ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def base_meta():
    return {
        "api_request_id": request_id(),
        "api_request_timestamp": db.now_iso(),
    }


def object_response(data, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def row_response(row, status=200):
    return object_response(serialize(row), status)


def list_response(rows, limit, offset, total_count, status=200):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(rows)) < total_count
    body = {
        "meta": meta,
        "response_type": "array",
        "data": [serialize(r) for r in rows],
    }
    return jsonify(body), status


def array_response(items, status=200):
    body = {
        "meta": base_meta(),
        "response_type": "array",
        "data": [serialize(i) if isinstance(i, dict) else i for i in items],
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
