"""Response envelope (PRD §2.2), pagination (§2.3), and request-body validators.

The structural schema gate (priority 3) raises ERR_INVALID_REQUEST / 400;
unknown body fields are ignored, never rejected.
"""

import json
import secrets
from decimal import Decimal

from flask import request, jsonify

from errors import ApiError, bad_request
from store import wall_ts_now, parse_dt


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def gen_request_id():
    return "req_" + secrets.token_hex(12)


def _meta():
    return {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": wall_ts_now(),
    }


def ok_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def list_response(items):
    """items: serialized dicts already sorted by creation order."""
    limit, offset = page_params()
    total = len(items)
    page = items[offset:offset + limit]
    meta = _meta()
    meta.update({
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    })
    return jsonify({"meta": meta, "response_type": "array", "data": page}), 200


def error_envelope(error_id, message):
    return {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# ---------------------------------------------------------------------------
# Pagination (limit default 10, min 1, max 100; offset default 0)
# ---------------------------------------------------------------------------

def page_params():
    try:
        limit = int(request.args.get("limit", 10))
    except (TypeError, ValueError):
        limit = 10
    try:
        offset = int(request.args.get("offset", 0))
    except (TypeError, ValueError):
        offset = 0
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


# ---------------------------------------------------------------------------
# Body access + validators (all schema violations -> ERR_INVALID_REQUEST/400)
# ---------------------------------------------------------------------------

def body():
    raw = request.get_data(as_text=True)
    if not raw or not raw.strip():
        return {}
    try:
        value = json.loads(raw)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, "request body is not valid JSON")
    if not isinstance(value, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "request body must be a JSON object")
    return value


def req_str(b, name):
    v = b.get(name)
    if not isinstance(v, str) or v == "":
        bad_request("%s is required and must be a non-empty string" % name)
    return v


def opt_str(b, name, default=None):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if not isinstance(v, str):
        bad_request("%s must be a string" % name)
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(b, name, lo=None, hi=None):
    v = b.get(name)
    if not _is_int(v):
        bad_request("%s is required and must be an integer" % name)
    if lo is not None and v < lo:
        bad_request("%s must be >= %s" % (name, lo))
    if hi is not None and v > hi:
        bad_request("%s must be <= %s" % (name, hi))
    return v


def opt_int(b, name, default=None, lo=None, hi=None):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if not _is_int(v):
        bad_request("%s must be an integer" % name)
    if lo is not None and v < lo:
        bad_request("%s must be >= %s" % (name, lo))
    if hi is not None and v > hi:
        bad_request("%s must be <= %s" % (name, hi))
    return v


def req_num(b, name, lo=None, hi=None):
    v = b.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        bad_request("%s is required and must be a number" % name)
    if lo is not None and v < lo:
        bad_request("%s must be >= %s" % (name, lo))
    if hi is not None and v > hi:
        bad_request("%s must be <= %s" % (name, hi))
    return v


def opt_bool(b, name, default=False):
    if name not in b or b[name] is None:
        return default
    v = b[name]
    if not isinstance(v, bool):
        bad_request("%s must be a boolean" % name)
    return v


def req_enum(b, name, values):
    v = b.get(name)
    if v not in values:
        bad_request("%s must be one of %s" % (name, ", ".join(values)))
    return v


def req_dt(b, name):
    v = b.get(name)
    if not isinstance(v, str) or v == "":
        bad_request("%s is required and must be an ISO 8601 timestamp" % name)
    try:
        return parse_dt(v)
    except (ValueError, OverflowError):
        bad_request("%s must be a valid ISO 8601 timestamp" % name)


def req_mark(b, name):
    """Committee pass mark: 0..10 inclusive, exactly one decimal place."""
    v = req_num(b, name, 0, 10)
    d = Decimal(str(v))
    if d != d.quantize(Decimal("0.1")):
        bad_request("%s must carry exactly one decimal place" % name)
    return v
