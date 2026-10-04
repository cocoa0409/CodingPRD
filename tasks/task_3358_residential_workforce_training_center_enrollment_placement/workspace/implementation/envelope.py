"""Response envelope helpers -- exact structure from PRD section 2.2."""
import uuid

from flask import jsonify

from db import STORE
from errors import ApiError


def _meta(pagination=None):
    m = {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": STORE.tick(),
    }
    if pagination is not None:
        m.update(pagination)
    return m


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(items, pagination):
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), 200


def error_response(err):
    if not isinstance(err, ApiError):
        err = ApiError("ERR_INTERNAL", 500, str(err))
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status
