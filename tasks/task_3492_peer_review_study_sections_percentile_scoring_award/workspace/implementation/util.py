"""Response envelope, pagination, datetime handling, auth, field validation."""
import uuid
from datetime import datetime, timezone

from flask import jsonify, request

from constants import (
    PAGINATION_DEFAULT_LIMIT,
    PAGINATION_DEFAULT_OFFSET,
    PAGINATION_MAX_LIMIT,
    PAGINATION_MIN_LIMIT,
)
from db import clock_now
from errors import fail


# ---------------------------------------------------------------------------
# Response envelope (scaffold §1.0 / PRD §2.2)
# ---------------------------------------------------------------------------
def _request_id():
    return "req_" + uuid.uuid4().hex[:20]


def _meta():
    return {
        "api_request_id": _request_id(),
        "api_request_timestamp": render_ts(clock_now()),
    }


def ok_object(data, code=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), code


def ok_list(items, total_count, limit, offset, code=200):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    body = {"meta": meta, "response_type": "array", "data": items}
    return jsonify(body), code


def error_body(err):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


# ---------------------------------------------------------------------------
# Datetime parsing / rendering (PRD §2.4)
# ---------------------------------------------------------------------------
def parse_iso(value):
    """Parse an ISO8601 UTC timestamp; returns aware datetime or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return None
    try:
        if dt.utcoffset() != timezone.utc.utcoffset(dt):
            return None
    except Exception:
        return None
    return dt.astimezone(timezone.utc)


def render_dt(dt):
    """Domain timestamps render as supplied/as the clock reads: second
    precision when whole, otherwise millisecond precision."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % millis


def render_ts(dt):
    """System timestamps (created_at/updated_at/api_request_timestamp):
    exactly three fractional digits (PRD §2.4)."""
    dt = dt.astimezone(timezone.utc)
    millis = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % millis


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def parse_pagination(args):
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = PAGINATION_DEFAULT_LIMIT
    else:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION_PARAMETERS", "limit must be an integer")
        if limit < PAGINATION_MIN_LIMIT or limit > PAGINATION_MAX_LIMIT:
            fail(
                "ERR_INVALID_PAGINATION_PARAMETERS",
                "limit must be within %d..%d"
                % (PAGINATION_MIN_LIMIT, PAGINATION_MAX_LIMIT),
            )
    if raw_offset is None:
        offset = PAGINATION_DEFAULT_OFFSET
    else:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            fail("ERR_INVALID_PAGINATION_PARAMETERS", "offset must be an integer")
        if offset < PAGINATION_DEFAULT_OFFSET:
            fail("ERR_INVALID_PAGINATION_PARAMETERS", "offset may not be negative")
    return limit, offset


def sort_and_page(items, limit, offset):
    """Default list ordering: created_at ascending (PRD §2.3); creation
    sequence breaks ties deterministically."""
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    return ordered[offset : offset + limit], total


# ---------------------------------------------------------------------------
# Auth (PRD §2.1, scaffold validations priority 1-2)
# ---------------------------------------------------------------------------
def auth_context():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or not user_id.strip() or not role.strip():
        fail(
            "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
            "X-User-ID and X-User-Role headers must be present and non-empty",
        )
    return user_id.strip(), role.strip()


def require_role(role, allowed):
    if role not in allowed:
        fail("ERR_UNAUTHORIZED_ROLE", "role %s is not authorized for this endpoint" % role)


def require_owner(owner_id, user_id):
    if owner_id != user_id:
        fail("ERR_NOT_RESOURCE_OWNER", "caller does not own this resource")


# ---------------------------------------------------------------------------
# Body handling + field validators (all raise ERR_VALIDATION)
# ---------------------------------------------------------------------------
def get_body():
    if request.data is None or request.data == b"":
        return {}
    data = request.get_json(silent=True)
    if data is None:
        fail("ERR_VALIDATION", "request body must be valid JSON")
    if not isinstance(data, dict):
        fail("ERR_VALIDATION", "request body must be a JSON object")
    return data


def _missing(body, name):
    return name not in body or body[name] is None


def req_str(body, name):
    if _missing(body, name):
        fail("ERR_VALIDATION", "missing required field: %s" % name)
    if not isinstance(body[name], str) or body[name] == "":
        fail("ERR_VALIDATION", "field %s must be a non-empty string" % name)
    return body[name]


def opt_str(body, name, default=None):
    if _missing(body, name):
        return default
    if not isinstance(body[name], str):
        fail("ERR_VALIDATION", "field %s must be a string" % name)
    return body[name]


def req_int(body, name, minimum=None, maximum=None):
    if _missing(body, name):
        fail("ERR_VALIDATION", "missing required field: %s" % name)
    return _check_int(body[name], name, minimum, maximum)


def opt_int(body, name, minimum=None, maximum=None, default=None):
    if _missing(body, name):
        return default
    return _check_int(body[name], name, minimum, maximum)


def _check_int(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_VALIDATION", "field %s must be an integer" % name)
    if minimum is not None and value < minimum:
        fail("ERR_VALIDATION", "field %s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_VALIDATION", "field %s must be <= %s" % (name, maximum))
    return value


def req_num(body, name, minimum=None, maximum=None):
    if _missing(body, name):
        fail("ERR_VALIDATION", "missing required field: %s" % name)
    return _check_num(body[name], name, minimum, maximum)


def opt_num(body, name, minimum=None, maximum=None, default=None):
    if _missing(body, name):
        return default
    return _check_num(body[name], name, minimum, maximum)


def _check_num(value, name, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_VALIDATION", "field %s must be a number" % name)
    if minimum is not None and value < minimum:
        fail("ERR_VALIDATION", "field %s must be >= %s" % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_VALIDATION", "field %s must be <= %s" % (name, maximum))
    return value


def req_bool(body, name):
    if _missing(body, name):
        fail("ERR_VALIDATION", "missing required field: %s" % name)
    if not isinstance(body[name], bool):
        fail("ERR_VALIDATION", "field %s must be a boolean" % name)
    return body[name]


def opt_bool(body, name, default=None):
    if _missing(body, name):
        return default
    if not isinstance(body[name], bool):
        fail("ERR_VALIDATION", "field %s must be a boolean" % name)
    return body[name]


def req_list(body, name, elem=None):
    if _missing(body, name):
        fail("ERR_VALIDATION", "missing required field: %s" % name)
    return _check_list(body[name], name, elem)


def opt_list(body, name, elem=None, default=None):
    if _missing(body, name):
        return default
    return _check_list(body[name], name, elem)


def _check_list(value, name, elem):
    if not isinstance(value, list):
        fail("ERR_VALIDATION", "field %s must be an array" % name)
    if elem is not None:
        for item in value:
            if elem is int:
                if isinstance(item, bool) or not isinstance(item, int):
                    fail("ERR_VALIDATION", "field %s must contain only integers" % name)
            elif not isinstance(item, elem):
                fail("ERR_VALIDATION", "field %s has an element of the wrong type" % name)
    return value


def req_enum(body, name, allowed):
    value = req_str(body, name)
    if value not in allowed:
        fail("ERR_VALIDATION", "field %s must be one of %s" % (name, ", ".join(allowed)))
    return value


def req_dt(body, name):
    raw = req_str(body, name)
    dt = parse_iso(raw)
    if dt is None:
        fail("ERR_VALIDATION", "field %s must be a valid ISO8601 UTC timestamp" % name)
    return dt


def opt_dt(body, name, default=None):
    if _missing(body, name):
        return default
    raw = body[name]
    if not isinstance(raw, str):
        fail("ERR_VALIDATION", "field %s must be a valid ISO8601 UTC timestamp" % name)
    dt = parse_iso(raw)
    if dt is None:
        fail("ERR_VALIDATION", "field %s must be a valid ISO8601 UTC timestamp" % name)
    return dt
