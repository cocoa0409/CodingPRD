"""Shared helpers: envelope, errors, timestamps, pagination, JSON body parsing."""

import datetime as dt
import random
import string
import uuid

from flask import jsonify, request

from store import now


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


def fail(error_id, http_status, message):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------
def now_iso():
    """Logical-clock timestamp rendered with exactly 3 fractional digits."""
    t = now()
    return "%s.%03dZ" % (t.strftime("%Y-%m-%dT%H:%M:%S"), t.microsecond // 1000)


def parse_dt(value):
    """Parse an ISO-8601 datetime string into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = dt.datetime.fromisoformat(s)
    except ValueError:
        # Fall back to date-only handling
        try:
            d = dt.datetime.combine(dt.date.fromisoformat(value.strip()), dt.time.min)
        except ValueError:
            raise ValueError("unparseable datetime")
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    else:
        d = d.astimezone(dt.timezone.utc)
    return d


def dt_iso(d):
    return "%s.%03dZ" % (d.strftime("%Y-%m-%dT%H:%M:%S"), d.microsecond // 1000)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta():
    return {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_uppercase + string.digits, k=24)
        ),
        "api_request_timestamp": now_iso(),
    }


def ok(data, status=200, extra_meta=None):
    resp_type = "array" if isinstance(data, list) else "object"
    if data is None:
        data = {}
    meta = _meta()
    if extra_meta:
        meta.update(extra_meta)
    resp = jsonify({"meta": meta, "response_type": resp_type, "data": data})
    resp.status_code = status
    return resp


def err_response(error_id, http_status, message):
    resp = jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    })
    resp.status_code = http_status
    return resp


# ---------------------------------------------------------------------------
# Entity lifecycle helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def fresh_entity(fields):
    """Attach common system fields to a new entity dict."""
    e = dict(fields)
    e["id"] = new_id()
    e["created_at"] = now_iso()
    e["updated_at"] = e["created_at"]
    e["version"] = 1
    return e


def bump(entity):
    """Advance version and refresh updated_at on an in-place mutation."""
    entity["version"] = entity.get("version", 1) + 1
    entity["updated_at"] = now_iso()


# ---------------------------------------------------------------------------
# Request body / pagination
# ---------------------------------------------------------------------------
def get_json():
    data = request.get_json(silent=True)
    if data is None or not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", 400, "Request body must be a JSON object")
    return data


def pagination_args():
    """Parse limit/offset. Defaults: limit=10 (min 1, max 100), offset=0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1:
            fail("ERR_INVALID_REQUEST", 400, "limit must be >= 1")
        if limit > 100:
            limit = 100
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def paged(items):
    """Sort by (created_at, id) ascending, paginate, and wrap in envelope."""
    items = sorted(items, key=lambda e: (e.get("created_at", ""), e.get("id", "")))
    limit, offset = pagination_args()
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return ok(page, 200, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    })
