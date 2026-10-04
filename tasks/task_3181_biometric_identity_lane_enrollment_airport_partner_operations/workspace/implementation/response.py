"""Response envelope helpers per PRD §2.2 / §2.3."""
import secrets
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(secrets.choice(alphabet) for _ in range(20))


def _wall_timestamp():
    # envelope timestamp is server-generated wall time, 3 fractional digits
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _meta(pagination=None):
    m = {
        "api_request_id": _request_id(),
        "api_request_timestamp": _wall_timestamp(),
    }
    if pagination:
        m.update(pagination)
    return m


def success(data, status_code=200, is_array=False, pagination=None):
    body = {
        "meta": _meta(pagination),
        "response_type": "array" if is_array else "object",
        "data": data if data is not None else ([] if is_array else {}),
    }
    return jsonify(body), status_code


def error(error_id, http_status, message):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status
