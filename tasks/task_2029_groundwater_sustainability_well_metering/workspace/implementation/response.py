"""Response envelope helpers per PRD §2.2 / SCAFFOLD §1.0."""
import secrets
from datetime import datetime, timezone

from flask import jsonify

from util import iso_ts


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(8),
        "api_request_timestamp": iso_ts(datetime.now(timezone.utc)),
    }


def ok(data, status=200, pagination=None, response_type="object"):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def ok_list(items, pagination, status=200):
    return ok(items, status=status, pagination=pagination, response_type="array")


def error_response(error_id, message, status):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
