"""Error type + response envelope helpers."""
import secrets
import string
from datetime import datetime, timezone
from flask import jsonify


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def _request_id():
    return "req_" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20))


def _stamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def ok(data, code=200, response_type="object", pagination=None):
    meta = {"api_request_id": _request_id(), "api_request_timestamp": _stamp()}
    if pagination is not None:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), code


def err(error_id, http_status, message):
    meta = {"api_request_id": _request_id(), "api_request_timestamp": _stamp()}
    return jsonify({
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }), http_status
