"""Shared helpers: error type, response envelope, pagination, parsing, rounding.

Envelope shape is exactly the PRD §2.2 contract:
  success: {"meta": {api_request_id, api_request_timestamp[, limit, offset,
            total_count, has_more]}, "response_type": "object"|"array", "data": ...}
  error:   {"meta": {api_request_id, api_request_timestamp},
            "response_type": "error", "data": {"error_id", "message"}}
"""

import random
import string
from datetime import date, datetime, timezone
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal

from flask import jsonify, request


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def err(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------

def _new_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _wall_timestamp():
    # Request metadata only; business rules never read wall-clock time.
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def base_meta():
    return {
        "api_request_id": _new_request_id(),
        "api_request_timestamp": _wall_timestamp(),
    }


def success_object(data, status=200):
    body = {"meta": base_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, total_count, limit, offset, status=200):
    meta = base_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error.error_id, "message": error.message},
    }
    return jsonify(body), error.http_status


# ---------------------------------------------------------------------------
# Request body / pagination
# ---------------------------------------------------------------------------

def get_body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return {}
    return data


def pagination_args():
    def parse_int(raw, default):
        if raw is None:
            return default
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    limit = parse_int(request.args.get("limit"), 10)
    offset = parse_int(request.args.get("offset"), 0)
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def paginate(records):
    """records: full list (already in creation order); returns a page."""
    limit, offset = pagination_args()
    total = len(records)
    page = records[offset:offset + limit]
    return success_list(page, total, limit, offset)


# ---------------------------------------------------------------------------
# Rounding (integer cents; Decimal only — never float money)
# ---------------------------------------------------------------------------

def round_half_up(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_down(value):
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_DOWN))


# ---------------------------------------------------------------------------
# Parsing and formatting
# ---------------------------------------------------------------------------

def parse_date_strict(value):
    """Strict ISO calendar date (YYYY-MM-DD); datetimes are rejected."""
    if not isinstance(value, str):
        return None
    if "T" in value or " " in value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def parse_datetime_lenient(value):
    """ISO 8601 datetime; accepts trailing Z, offsets, fractional seconds.

    Naive values are interpreted as UTC.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fmt_ts(dt):
    """Canonical timestamp: ISO 8601 UTC with three fractional digits."""
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def require_str(body, field):
    value = body.get(field)
    if value is None or not isinstance(value, str):
        err("ERR_INVALID_REQUEST", 400, "Field '%s' is required and must be a string" % field)
    return value


def require_int(body, field):
    value = body.get(field)
    if value is None or not is_int(value):
        err("ERR_INVALID_REQUEST", 400, "Field '%s' is required and must be an integer" % field)
    return value


def require_present(body, field):
    value = body.get(field)
    if value is None:
        err("ERR_INVALID_REQUEST", 400, "Field '%s' is required" % field)
    return value


def optional_bool(body, field):
    value = body.get(field)
    if value is None:
        return False
    if not isinstance(value, bool):
        err("ERR_INVALID_REQUEST", 400, "Field '%s' must be a boolean" % field)
    return value
