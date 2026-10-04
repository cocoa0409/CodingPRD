import re
import uuid
from datetime import datetime, timedelta, timezone

from flask import jsonify, request

from errors import ApiError

_TS_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$"
)


def fmt_ts(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    return f"{base}.{dt.microsecond // 1000:03d}Z"


def fmt_instant(dt):
    """Format for logical-clock-derived instants (shipped_at, due_at,
    response_due_at, valid_until, assessed_at, collected_at, schedule
    windows). The logical clock is pinned in PRD as reading exactly
    2026-09-01T00:00:00Z, so second-precision instants emit without a
    fractional part; fractional digits appear only when non-zero."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    if ms:
        return f"{base}.{ms:03d}Z"
    return f"{base}Z"


def parse_ts(value):
    if not isinstance(value, str) or not _TS_RE.match(value):
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid timestamp: %r" % (value,))
    s = value
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    else:
        # normalize +0000 -> +00:00
        if len(s) >= 5 and s[-5] in "+-" and s[-2] != ":":
            s = s[:-2] + ":" + s[-2:]
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ApiError("ERR_INVALID_REQUEST", 400, "invalid timestamp: %r" % (value,))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def success(data, status=200, pagination=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }
    if isinstance(data, list):
        response_type = "array"
    else:
        response_type = "object"
    if pagination is not None:
        meta["limit"] = pagination["limit"]
        meta["offset"] = pagination["offset"]
        meta["total_count"] = pagination["total_count"]
        meta["has_more"] = pagination["has_more"]
    body = {"meta": meta, "response_type": response_type, "data": data}
    resp = jsonify(body)
    resp.status_code = status
    return resp


def error_response(err):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": fmt_ts(datetime.now(timezone.utc)),
    }
    body = {
        "meta": meta,
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    resp = jsonify(body)
    resp.status_code = err.status
    return resp


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "invalid limit")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit out of range")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "invalid offset")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset out of range")
    return limit, offset


def list_response(items, sort_key=None):
    """items: raw records (may contain _-prefixed internals). Paginates, sorts by
    created_at asc with an insertion-sequence tiebreak, strips internals."""
    limit, offset = pagination_params()
    key = sort_key or (lambda r: (r.get("created_at", ""), r.get("_seq", 0)))
    ordered = sorted(items, key=key)
    total = len(ordered)
    page = ordered[offset : offset + limit]
    has_more = (offset + limit) < total
    stripped = [{k: v for k, v in r.items() if not k.startswith("_")} for r in page]
    return success(
        stripped,
        status=200,
        pagination={
            "limit": limit,
            "offset": offset,
            "total_count": total,
            "has_more": has_more,
        },
    )


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool))
