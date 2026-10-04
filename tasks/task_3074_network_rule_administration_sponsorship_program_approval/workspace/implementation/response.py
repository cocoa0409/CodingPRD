"""Response envelope helpers, timestamp/UUID utilities."""

import random
import string
from datetime import datetime, timezone

from flask import jsonify

from errors import ApiError


def _req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _now_iso():
    """Wall-clock timestamp with 3 fractional digits for meta (not the logical clock)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def iso3(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def ok(data, status=200, pagination=None):
    meta = {"api_request_id": _req_id(), "api_request_timestamp": _now_iso()}
    if pagination is not None:
        meta.update(pagination)
    resp_type = "array" if isinstance(data, list) else "object"
    body = {"meta": meta, "response_type": resp_type, "data": data}
    return jsonify(body), status


def error_response(err: ApiError):
    body = {
        "meta": {"api_request_id": _req_id(), "api_request_timestamp": _now_iso()},
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status
