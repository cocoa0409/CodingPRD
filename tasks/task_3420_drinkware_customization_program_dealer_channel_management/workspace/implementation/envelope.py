"""Response envelope, timestamps, ids, pagination, and request-body validators.

Envelope shape is read from SCAFFOLD.yaml §1.0 / PRD §2.2:
success: {"meta": {api_request_id, api_request_timestamp[, limit, offset,
total_count, has_more]}, "response_type": "object"|"array", "data": ...}
error:   {"meta": {api_request_id, api_request_timestamp},
          "response_type": "error", "data": {error_id, message}}
Entity timestamps (created_at/updated_at/filed_at/...) read the logical clock;
meta.api_request_timestamp is wall-clock UTC. Both use 3 fractional digits.
"""
import uuid
from datetime import datetime, timezone

from flask import jsonify, request

from errors import fail
from store import get_clock


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits and a Z suffix."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_ts():
    """Current logical-clock timestamp (entity created_at/updated_at)."""
    return fmt_dt(get_clock())


def wall_ts():
    """Wall-clock UTC timestamp for meta.api_request_timestamp."""
    return fmt_dt(datetime.now(timezone.utc))


def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + uuid.uuid4().hex[:24]


def parse_dt(value, field):
    if not isinstance(value, str):
        fail("ERR_INVALID_REQUEST", "%s must be an ISO8601 timestamp string" % field)
    txt = value.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        fail("ERR_INVALID_REQUEST", "%s must be a valid ISO8601 timestamp" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return body


# ---------------------------------------------------------------------------
# Field validators — every failure is ERR_INVALID_REQUEST (400).
# ---------------------------------------------------------------------------

def _missing(body, name):
    return name not in body or body[name] is None


def req_str(body, name):
    if _missing(body, name) or not isinstance(body[name], str):
        fail("ERR_INVALID_REQUEST", "%s is required and must be a string" % name)
    return body[name]


def opt_str(body, name):
    if _missing(body, name):
        return None
    if not isinstance(body[name], str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % name)
    return body[name]


def req_int(body, name, minimum=None, maximum=None):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        fail("ERR_INVALID_REQUEST", "%s is required and must be an integer" % name)
    if minimum is not None and v < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s" % (name, minimum))
    if maximum is not None and v > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s" % (name, maximum))
    return v


def opt_int(body, name, minimum=None, maximum=None):
    if _missing(body, name):
        return None
    return req_int(body, name, minimum, maximum)


def req_number(body, name, minimum=None, maximum=None):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        fail("ERR_INVALID_REQUEST", "%s is required and must be a number" % name)
    if minimum is not None and v < minimum:
        fail("ERR_INVALID_REQUEST", "%s must be >= %s" % (name, minimum))
    if maximum is not None and v > maximum:
        fail("ERR_INVALID_REQUEST", "%s must be <= %s" % (name, maximum))
    return v


def req_bool(body, name):
    v = body.get(name)
    if not isinstance(v, bool):
        fail("ERR_INVALID_REQUEST", "%s is required and must be a boolean" % name)
    return v


def req_enum(body, name, values):
    v = body.get(name)
    if not isinstance(v, str) or v not in values:
        fail("ERR_INVALID_REQUEST", "%s must be one of %s" % (name, "|".join(values)))
    return v


def opt_enum(body, name, values):
    if _missing(body, name):
        return None
    return req_enum(body, name, values)


def req_dt(body, name):
    if _missing(body, name):
        fail("ERR_INVALID_REQUEST", "%s is required" % name)
    return parse_dt(body[name], name)


def opt_dt(body, name):
    if _missing(body, name):
        return None
    return parse_dt(body[name], name)


def req_str_array(body, name):
    v = body.get(name)
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        fail("ERR_INVALID_REQUEST", "%s must be an array of strings" % name)
    return v


# ---------------------------------------------------------------------------
# Envelope responses
# ---------------------------------------------------------------------------

def success(data, code=200):
    payload = {
        "meta": {"api_request_id": request_id(), "api_request_timestamp": wall_ts()},
        "response_type": "object",
        "data": data,
    }
    return jsonify(payload), code


def success_list(items):
    page, pg = paginate(items)
    meta = {"api_request_id": request_id(), "api_request_timestamp": wall_ts()}
    meta.update(pg)
    return jsonify({"meta": meta, "response_type": "array", "data": page}), 200


def error_response(err):
    payload = {
        "meta": {"api_request_id": request_id(), "api_request_timestamp": wall_ts()},
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(payload), err.http_status


def paginate(items):
    """limit (default 10, min 1, max 100) / offset (default 0) pagination."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1 or limit > 100:
            fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            fail("ERR_INVALID_REQUEST", "offset must be >= 0")
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    return page, {"limit": limit, "offset": offset,
                  "total_count": total, "has_more": has_more}


def sort_created(items):
    """Default sort: created_at ASC; stable, so equal timestamps keep
    creation (insertion) order."""
    return sorted(items, key=lambda e: e["created_at"])


def new_entity(extra=None):
    ts = now_ts()
    e = {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1}
    if extra:
        e.update(extra)
    return e


def touch(entity):
    """Every mutation — including cascading side effects — refreshes
    updated_at and increments version by exactly 1 (PRD §2.5)."""
    entity["updated_at"] = now_ts()
    entity["version"] += 1
