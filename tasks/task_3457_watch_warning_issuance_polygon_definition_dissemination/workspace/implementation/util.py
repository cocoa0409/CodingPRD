"""Envelope, timestamps, rounding, pagination, and request-body helpers."""
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import jsonify, request

from constants import DEFAULT_LIMIT, DEFAULT_OFFSET, MAX_LIMIT, MIN_LIMIT
from db import next_seq, now


# ---------------------------------------------------------------------------
# identifiers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def new_req_id():
    return "req_" + "".join(random.choices(string.ascii_uppercase + string.digits, k=16))


# ---------------------------------------------------------------------------
# datetimes — everything comes from the logical clock; comparisons resolve to
# the second, so parsed inputs are truncated to whole seconds.
# ---------------------------------------------------------------------------
def fmt_dt(dt):
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO 8601 string to an aware UTC datetime truncated to seconds."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


# ---------------------------------------------------------------------------
# rounding — round-half-up everywhere (PRD §2.5)
# ---------------------------------------------------------------------------
def round_half_up_dec(value, places):
    q = Decimal(1).scaleb(-places)
    return Decimal(repr(float(value))).quantize(q, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------------------
# response envelope (PRD §2.2 / SCAFFOLD §1.0)
# ---------------------------------------------------------------------------
def envelope(data, response_type="object", status=200, pagination=None):
    meta = {"api_request_id": new_req_id(), "api_request_timestamp": fmt_dt(now())}
    if pagination is not None:
        meta.update(pagination)
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), status


def error_envelope(err):
    meta = {"api_request_id": new_req_id(), "api_request_timestamp": fmt_dt(now())}
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    try:
        limit = int(raw_limit) if raw_limit is not None else DEFAULT_LIMIT
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    limit = max(MIN_LIMIT, min(MAX_LIMIT, limit))
    try:
        offset = int(raw_offset) if raw_offset is not None else DEFAULT_OFFSET
    except (TypeError, ValueError):
        offset = DEFAULT_OFFSET
    offset = max(0, offset)
    return limit, offset


def list_response(items, serializer):
    """items must already be filtered; sorts by creation ascending (PRD §2.3)."""
    ordered = sorted(items, key=lambda e: e["_seq"])
    limit, offset = pagination_params()
    total = len(ordered)
    page = ordered[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return envelope([serializer(x) for x in page], "array", 200, pagination)


# ---------------------------------------------------------------------------
# entity helpers
# ---------------------------------------------------------------------------
def base_entity():
    ts = now()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    """Every mutation refreshes updated_at and increments version (PRD §2.4/§2.9)."""
    entity["updated_at"] = now()
    entity["version"] += 1


def get_body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


# ---------------------------------------------------------------------------
# coercion helpers (return None when not coercible)
# ---------------------------------------------------------------------------
def as_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def as_int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            parsed = float(value)
        except ValueError:
            return None
        if parsed.is_integer():
            return int(parsed)
    return None
