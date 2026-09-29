"""Response envelope helpers (PRD 2.2 / 2.3)."""

import uuid

from flask import jsonify

from store import now_instant

_ALNUM_LEN = 24


def _meta():
    token = uuid.uuid4().hex[:_ALNUM_LEN]
    return {
        "api_request_id": "req_" + token,
        "api_request_timestamp": now_instant(),
    }


def object_response(data, status=200):
    body = {
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }
    return jsonify(body), status


def list_response(items, page, status=200):
    """`page` is the dict of the four pagination fields."""
    meta = _meta()
    meta.update(page)
    body = {
        "meta": meta,
        "response_type": "array",
        "data": items,
        "pagination": dict(page),
    }
    return jsonify(body), status


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }
    return jsonify(body), status
