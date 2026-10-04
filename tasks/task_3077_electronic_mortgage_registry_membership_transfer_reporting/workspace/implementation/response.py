"""Standard response envelope helpers (PRD §2.2 / §2.3)."""
import random
import string
from datetime import datetime, timezone

from flask import jsonify


def _request_id() -> str:
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _request_ts() -> str:
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def success(data, status=200, is_list=False, pagination=None):
    meta = {"api_request_id": _request_id(), "api_request_timestamp": _request_ts()}
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if is_list else "object",
        "data": data,
    }
    return jsonify(body), status


def error(api_error):
    body = {
        "meta": {"api_request_id": _request_id(), "api_request_timestamp": _request_ts()},
        "response_type": "error",
        "data": {"error_id": api_error.error_id, "message": api_error.message},
    }
    return jsonify(body), api_error.http_status
