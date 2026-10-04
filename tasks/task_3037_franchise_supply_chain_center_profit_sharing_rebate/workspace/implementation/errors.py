"""Error types and response envelope helpers per PRD §2.2."""
import random
import string
from datetime import datetime, timezone, timedelta

from flask import jsonify

from db import db


class ApiError(Exception):
    def __init__(self, error_id, message, http_status):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


def _request_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=20))


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": format_ts(db.clock.now()),
    }


def ok(data, status=200, pagination=None):
    body = {
        "meta": _meta(),
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    if pagination is not None:
        body["meta"].update(pagination)
    return jsonify(body), status


def error_response(err: ApiError):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def parse_ts(value, field="timestamp"):
    """Parse an ISO-8601 timestamp into an aware datetime. Raises ERR_INVALID_REQUEST."""
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", f"{field} must be an ISO 8601 string", 400)
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", f"{field} is not a valid ISO 8601 timestamp", 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def format_ts(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits and 'Z'."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ms:03d}Z"


def week_of(dt: datetime) -> datetime:
    """Monday 00:00:00 UTC of the week containing dt."""
    d = dt.astimezone(timezone.utc)
    monday = (d - timedelta(days=d.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    return monday
