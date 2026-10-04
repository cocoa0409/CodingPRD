"""Response envelope, pagination, rounding, and scalar validation helpers."""
import uuid
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

import clock
import constants as C
from errors import ApiError


# ---------------------------------------------------------------- ids / meta
def new_id():
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + uuid.uuid4().hex


def meta():
    return {
        "api_request_id": new_request_id(),
        "api_request_timestamp": clock.now_iso(),
    }


# ---------------------------------------------------------------- envelope
def ok(data, code=200):
    body = {"meta": meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def error_response(error_id, message, status):
    body = {
        "meta": meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), status


# ---------------------------------------------------------------- pagination
def parse_pagination():
    """limit: default 10, min 1, max 100. offset: default 0, min 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else 10
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
    try:
        offset = int(raw_offset) if raw_offset is not None else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def list_response(items, serialize):
    """Sorted by created_at ascending (stable tiebreak on insertion order)."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda e: (e.get("created_at", ""), e.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    m = meta()
    m["limit"] = limit
    m["offset"] = offset
    m["total_count"] = total
    m["has_more"] = (offset + len(page)) < total
    body = {
        "meta": m,
        "response_type": "array",
        "data": [serialize(e) for e in page],
    }
    return jsonify(body), 200


# ---------------------------------------------------------------- rounding
def round_half_up_int(value):
    """Round a Decimal to integer (half up)."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(value):
    """Round a Decimal to 2 decimal places (half up); returned as a JSON number."""
    return float(Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def msy_3dp(total_minutes):
    """member-service years to exactly 3 decimal places; returned as a number."""
    return float(
        (Decimal(total_minutes) / Decimal(C.MSY_MINUTES)).quantize(
            Decimal("0.001"), rounding=ROUND_HALF_UP
        )
    )


def federal_basis_cents(federal_share_cents, total_term_minutes):
    """The rounded-2dp federal-basis cost per MSY as an exact Decimal."""
    return (Decimal(federal_share_cents) * Decimal(C.MSY_MINUTES) / Decimal(total_term_minutes)).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


# ---------------------------------------------------------------- dates
def parse_date(value):
    """Parse an ISO calendar date (YYYY-MM-DD). Returns a date or None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def add_years_date(d, years):
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # Feb 29 -> Feb 28
        return d.replace(year=d.year + years, day=28)


def add_years_datetime(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        return dt.replace(year=dt.year + years, day=28)


# ---------------------------------------------------------------- scalars
def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_str(v):
    return isinstance(v, str)


def body_json():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}
