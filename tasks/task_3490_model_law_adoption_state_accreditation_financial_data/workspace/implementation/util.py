"""Response envelope, timestamp rendering, pagination, and request-shape helpers.

Timestamp rendering has two families (PRD 2.2 vs 2.4):
  - created_at / updated_at / api_request_timestamp: exactly 3 fractional digits.
  - all other domain timestamps (windows, cast_at, published_at, enacted_on,
    period bounds, effective_from, valid_until): rendered as the clock reads,
    i.e. ISO 8601 UTC with no forced fractional part.
"""

import secrets
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, getcontext

from flask import request, jsonify

from errors import ApiError

getcontext().prec = 60


# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

def new_request_id():
    return "req_" + secrets.token_hex(12)


def _iso3(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wallclock_iso3():
    """api_request_timestamp: server wall clock, 3 fractional digits."""
    return _iso3(datetime.now(timezone.utc))


def meta_base():
    return {"api_request_id": new_request_id(), "api_request_timestamp": wallclock_iso3()}


def ok_object(data, status=200):
    body = {"meta": meta_base(), "response_type": "object", "data": data}
    return jsonify(body), status


def ok_list(serialized_items, total_count, limit, offset):
    meta = meta_base()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(serialized_items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": serialized_items}), 200


def error_body(err):
    return {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------

def iso3(dt):
    """created_at / updated_at rendering: always 3 fractional digits."""
    return _iso3(dt)


def iso_domain(dt):
    """Domain timestamps render as the logical clock reads (no forced fraction)."""
    if dt is None:
        return None
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    if dt.microsecond % 1000 == 0:
        return _iso3(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%06dZ" % dt.microsecond


def parse_ts(value, field):
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an ISO 8601 timestamp string" % field, 400)
    s = value.strip()
    if s.endswith("Z") or s.endswith("z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", "%s is not a valid ISO 8601 timestamp" % field, 400)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Pagination and list helpers
# ---------------------------------------------------------------------------

def pagination_params():
    """limit/offset per PRD 2.3: default 10/0, limit clamped to [1, 100]."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer", 400)
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer", 400)
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    return limit, offset


def sorted_recs(recs):
    """List responses are sorted by created_at ascending (PRD 2.3)."""
    return sorted(recs, key=lambda r: (r["created_at"], r["_seq"]))


def paginate(recs, serializer):
    limit, offset = pagination_params()
    ordered = sorted_recs(recs)
    page = ordered[offset:offset + limit]
    return ok_list([serializer(r) for r in page], len(ordered), limit, offset)


# ---------------------------------------------------------------------------
# Request body shape helpers (stage 5; ERR_INVALID_REQUEST, 400)
# ---------------------------------------------------------------------------

def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "Request body must be a JSON object", 400)
    return data


def req_field(body, name):
    if name not in body or body[name] is None:
        raise ApiError("ERR_INVALID_REQUEST", "Missing required field: %s" % name, 400)
    return body[name]


def req_str(body, name):
    v = req_field(body, name)
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a string" % name, 400)
    return v


def req_enum(body, name, allowed):
    v = req_field(body, name)
    if v not in allowed:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "%s must be one of %s" % (name, ", ".join(sorted(allowed))),
            400,
        )
    return v


def req_int(body, name, minimum=None):
    v = req_field(body, name)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be an integer" % name, 400)
    if minimum is not None and v < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be >= %d" % (name, minimum), 400)
    return v


def req_ts(body, name):
    return parse_ts(req_field(body, name), name)


def opt_bool(body, name, default=False):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", "%s must be a boolean" % name, 400)
    return v


def req_count_pair(body, compliant_name, total_name):
    """findings/self-assessment counts: total >= 1, 0 <= compliant <= total."""
    total = req_int(body, total_name)
    compliant = req_int(body, compliant_name)
    if total < 1:
        raise ApiError("ERR_INVALID_REQUEST", "%s must be >= 1" % total_name, 400)
    if compliant < 0 or compliant > total:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "%s must lie between 0 and %s" % (compliant_name, total_name),
            400,
        )
    return compliant, total


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------

def rhu(value, places):
    """Round half-up to `places` decimal places (PRD 2.5)."""
    quantum = Decimal(1).scaleb(-places)
    return value.quantize(quantum, rounding=ROUND_HALF_UP)


def num(v):
    """JSON-ready rendering of stored Decimal/int/None numerics."""
    if v is None:
        return None
    if isinstance(v, Decimal):
        return float(v)
    return v
