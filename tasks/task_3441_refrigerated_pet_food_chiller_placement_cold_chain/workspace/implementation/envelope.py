"""Response envelope helpers per scaffold response_envelope / PRD section 2.2.

Success: { "meta": {api_request_id, api_request_timestamp[, pagination]},
           "response_type": "object"|"array", "data": ... }
Error:   { "meta": {...}, "response_type": "error",
           "data": {"error_id": ..., "message": ...} }
"""
import secrets
from datetime import datetime, timezone

from flask import jsonify

from state import fmt_dt_ms


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(8),
        "api_request_timestamp": fmt_dt_ms(datetime.now(timezone.utc)),
    }


def ok(data, response_type="object", status=200, pagination=None):
    m = _meta()
    if pagination is not None:
        m.update(pagination)
    body = {"meta": m, "response_type": response_type, "data": data}
    return jsonify(body), status


def err(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
