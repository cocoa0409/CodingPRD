"""Shared helpers: timestamps, Decimal rounding, response envelope, pagination,
request-body validators, research momentum. No domain state lives here."""

import secrets
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, getcontext
from fractions import Fraction

from flask import jsonify, request

from constants import CONSTANTS
from errors import ApiError

getcontext().prec = 60

# ---------------------------------------------------------------------------
# time
# ---------------------------------------------------------------------------


def wall_now():
    """Wall-clock UTC — used only for meta.api_request_timestamp (request receipt).
    All entity timestamps and time-derived rules use the logical clock (state.now)."""
    return datetime.now(timezone.utc)


def fmt_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-09-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 datetime; returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s[-1] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# decimals (round-half-up, ties away from zero)
# ---------------------------------------------------------------------------


def dec(x):
    return Decimal(str(x))


def q2(x):
    return x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def q4(x):
    return x.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def q0int(x):
    return int(x.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# response envelope (SCAFFOLD response_envelope / PRD §2.2)
# ---------------------------------------------------------------------------


def _meta():
    return {
        "api_request_id": "req_" + secrets.token_hex(12),
        "api_request_timestamp": fmt_iso(wall_now()),
    }


def ok_object(data, code=200):
    return jsonify({"meta": _meta(), "response_type": "object", "data": data}), code


def ok_list(items, total_count, limit, offset):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({"meta": meta, "response_type": "array", "data": items}), 200


def error_response(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.status


# ---------------------------------------------------------------------------
# pagination (limit/offset; defaults 10/0, limit in [1, 100])
# ---------------------------------------------------------------------------


def _parse_int_arg(name, raw, default, min_v, max_v):
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "query parameter %r must be an integer" % name)
    if value < min_v or value > max_v:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "query parameter %r out of range" % name)
    return value


def by_creation(items):
    """Every list endpoint sorts by creation ascending; seq is a monotonic
    insertion counter (stable tiebreak when the logical clock is frozen)."""
    return sorted(items, key=lambda e: e["seq"])


def paginate(items):
    limit = _parse_int_arg("limit", request.args.get("limit"), 10, 1, 100)
    offset = _parse_int_arg("offset", request.args.get("offset"), 0, 0, 1 << 62)
    total = len(items)
    return ok_list(items[offset:offset + limit], total, limit, offset)


# ---------------------------------------------------------------------------
# request body validators (all failures -> ERR_INVALID_REQUEST 400)
# ---------------------------------------------------------------------------


def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", 400, "request body must be a JSON object")
    return data


def req_string(data, field):
    v = data.get(field)
    if not isinstance(v, str) or not v.strip():
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "field %r is required and must be a non-empty string" % field)
    return v


def opt_string(data, field):
    v = data.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, "field %r must be a string" % field)
    return v


def req_int(data, field, min_v=None, max_v=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "field %r is required and must be an integer" % field)
    if min_v is not None and v < min_v:
        raise ApiError("ERR_INVALID_REQUEST", 400, "field %r is below its minimum" % field)
    if max_v is not None and v > max_v:
        raise ApiError("ERR_INVALID_REQUEST", 400, "field %r exceeds its maximum" % field)
    return v


def req_number(data, field):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "field %r is required and must be a number" % field)
    return v


def req_bool(data, field):
    v = data.get(field)
    if not isinstance(v, bool):
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "field %r is required and must be a boolean" % field)
    return v


def req_dt(data, field):
    dt = parse_iso(data.get(field))
    if dt is None:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "field %r is required and must be an ISO 8601 datetime" % field)
    return dt


def req_enum(data, field, allowed):
    v = data.get(field)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400,
                       "field %r must be one of %s" % (field, sorted(allowed)))
    return v


# ---------------------------------------------------------------------------
# research momentum: sum(points * 0.85 ** full_weeks_old), half-up 2dp
# ---------------------------------------------------------------------------

_WEEK_SECONDS = 7 * 24 * 3600


def momentum_score(insights, now):
    """Exact rational arithmetic: the decay factor is a terminating decimal, so
    Fraction powers stay exact for any week count; rounding happens once at 2dp."""
    decay = Fraction(Decimal(CONSTANTS["RESEARCH_DECAY_PER_WEEK"]))
    total = Fraction(0)
    for ins in insights:
        delta = (now - ins["observed_dt"]).total_seconds()
        weeks = int(delta // _WEEK_SECONDS)
        if weeks < 0:
            weeks = 0
        total += ins["points"] * (decay ** weeks)
    result = Decimal(total.numerator) / Decimal(total.denominator)
    return q2(result)
