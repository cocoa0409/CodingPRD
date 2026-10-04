"""Response envelope, pagination, datetime codecs, and request-body validators.

Envelope shape (PRD 2.2 / scaffold response_envelope):
  success: {"meta": {"api_request_id", "api_request_timestamp", [pagination]},
            "response_type": "object" | "array", "data": ...}
  error:   {"meta": {"api_request_id", "api_request_timestamp"},
            "response_type": "error", "data": {"error_id", "message"}}
Pagination fields in meta: limit, offset, total_count, has_more
(defaults: limit 10, min 1, max 100, offset 0).

Datetime policy (PRD 2.8): inputs are compared to the second, so they are
truncated to whole seconds on parse; echoes serialize without a fractional
part. System wall timestamps (created_at / updated_at / api_request_timestamp)
always carry exactly three fractional digits.
"""

import re
import uuid
from datetime import datetime, timezone

from flask import jsonify, request

from errors import ApiError
from storage import get_clock

_INT_RE = re.compile(r"-?\d+")


# --- Timestamp formatting ----------------------------------------------------
def fmt_ts(dt):
    """System timestamps: ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_dt(dt):
    """Domain datetimes (inputs echoed back, logical-clock stamps): whole
    seconds serialize without a fraction; sub-second values (not producible
    from truncated inputs) keep three fractional digits."""
    if dt is None:
        return None
    if dt.microsecond:
        return fmt_ts(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_dt(value, field="timestamp"):
    """Parse an ISO 8601 UTC datetime input, truncated to whole seconds."""
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO 8601 string" % field)
    text = value.strip()
    candidate = text[:-1] + "+00:00" if text.endswith(("Z", "z")) else text
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        raise ApiError(
            "ERR_INVALID_REQUEST", "%s is not a valid ISO 8601 datetime" % field
        )
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0)


# --- Envelope ------------------------------------------------------------------
def _request_meta():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": fmt_ts(get_clock()),
    }


def success_object(data, status=200):
    body = {"meta": _request_meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, total_count, limit, offset, status=200):
    meta = _request_meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), status


def error_response(error_id, message, http_status):
    body = {
        "meta": _request_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


# --- Pagination ---------------------------------------------------------------
def pagination_params():
    """Parse limit/offset query params per PRD 2.3 (default 10/0, limit in
    [1,100]; malformed values fail with ERR_INVALID_REQUEST)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        if not _INT_RE.fullmatch(raw_limit.strip()):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        limit = int(raw_limit)
        if limit < 1 or limit > 100:
            raise ApiError(
                "ERR_INVALID_REQUEST", "limit must be between 1 and 100"
            )
    if raw_offset is not None:
        if not _INT_RE.fullmatch(raw_offset.strip()):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        offset = int(raw_offset)
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", "offset must be >= 0")
    return limit, offset


def paginate(records):
    """Apply pagination to an already-ordered list and build the response."""
    limit, offset = pagination_params()
    total = len(records)
    page = records[offset : offset + limit]
    return success_list(page, total, limit, offset)


# --- Body parsing and field validators -----------------------------------------
def body_json():
    """Return the request JSON object; {} when no body was sent. A present but
    unparseable or non-object body is malformed (ERR_INVALID_REQUEST)."""
    raw = request.get_data()
    if raw is None or len(raw) == 0:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise ApiError("ERR_INVALID_REQUEST", "request body must be valid JSON")
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def _missing(body, name):
    return name not in body or body[name] is None


def req_str(body, name):
    if _missing(body, name) or not isinstance(body[name], str):
        raise ApiError("ERR_INVALID_REQUEST", "%s is required and must be a string" % name)
    return body[name]


def opt_str(body, name, default=None):
    if _missing(body, name):
        return default
    if not isinstance(body[name], str):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a string" % name)
    return body[name]


def _is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def req_int(body, name):
    if _missing(body, name) or not _is_int(body[name]):
        raise ApiError(
            "ERR_INVALID_REQUEST", "%s is required and must be an integer" % name
        )
    return body[name]


def opt_int(body, name, default=None):
    if _missing(body, name):
        return default
    if not _is_int(body[name]):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    return body[name]


def opt_bool(body, name, default=None):
    if _missing(body, name):
        return default
    if not isinstance(body[name], bool):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a boolean" % name)
    return body[name]


def req_enum(body, name, allowed):
    value = req_str(body, name)
    if value not in allowed:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "%s must be one of %s" % (name, ", ".join(allowed)),
        )
    return value


def opt_enum(body, name, allowed, default=None):
    if _missing(body, name):
        return default
    return req_enum(body, name, allowed)


def req_dt(body, name):
    if _missing(body, name):
        raise ApiError("ERR_INVALID_REQUEST", "%s is required" % name)
    return parse_dt(body[name], name)


def opt_dt(body, name, default=None):
    if _missing(body, name):
        return default
    return parse_dt(body[name], name)
