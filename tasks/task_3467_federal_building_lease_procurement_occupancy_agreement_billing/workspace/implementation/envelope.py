"""Response envelope per PRD section 2.2.

Success: {"meta": {"api_request_id", "api_request_timestamp", [pagination]},
          "response_type": "object" | "array", "data": ...}
Error:   {"meta": {"api_request_id", "api_request_timestamp"},
          "response_type": "error", "data": {"error_id", "message"}}
The meta timestamp is the wall clock (per-request metadata); business
timestamps read the logical clock instead.
"""
import secrets
from datetime import datetime, timezone

from flask import jsonify


def _meta():
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    return {"api_request_id": "req_" + secrets.token_hex(8), "api_request_timestamp": ts}


def success(data, code=200, pagination=None):
    meta = _meta()
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if pagination is not None else "object",
        "data": data,
    }
    return jsonify(body), code


def error_resp(error_id, status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status
