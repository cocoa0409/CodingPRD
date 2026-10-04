"""HTTP plumbing: response envelope (scaffold 1.0 / PRD 2.2), auth (PRD 2.1),
pagination (PRD 2.3), and request-body schema helpers (PRD 2.7 priority 5)."""
import uuid
from datetime import datetime

from flask import jsonify, request

import db
from constants import (
    ALL_ROLES,
    HEADER_USER_ID,
    HEADER_USER_ROLE,
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MAX,
    PAGE_LIMIT_MIN,
    PAGE_OFFSET_DEFAULT,
)
from errors import ApiError


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def _meta(pagination=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": db.iso(db.now()),
    }
    if pagination is not None:
        meta.update(pagination)
    return meta


def success_object(data, status=200):
    body = {"meta": _meta(), "response_type": "object", "data": data}
    return jsonify(body), status


def success_list(items, pagination, status=200):
    body = {
        "meta": _meta(pagination),
        "response_type": "array",
        "data": items,
    }
    return jsonify(body), status


def success_wrapped_list(wrapper_key, items, pagination, status=200):
    """List-like endpoints whose data payload is an object wrapping the rows
    (e.g. GET /scam-patterns -> data.patterns)."""
    body = {
        "meta": _meta(pagination),
        "response_type": "object",
        "data": {wrapper_key: items},
    }
    return jsonify(body), status


def error_response(error):
    body = {
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": error.error_id, "message": error.message},
    }
    return jsonify(body), error.http_status


# ---------------------------------------------------------------------------
# Auth (PRD 2.1, validation priorities 1-2)
# ---------------------------------------------------------------------------
def authenticate():
    """Priority 1: headers present and role known. Returns (user_id, role)."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if not user_id or not role or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def require_role(role, allowed_roles):
    """Priority 2: the role must be listed among the endpoint's roles."""
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED")


def authz(allowed_roles):
    """Combined priorities 1+2. Returns (user_id, role)."""
    user_id, role = authenticate()
    require_role(role, allowed_roles)
    return user_id, role


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3)
# ---------------------------------------------------------------------------
def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = PAGE_LIMIT_DEFAULT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer")
        limit = max(PAGE_LIMIT_MIN, min(PAGE_LIMIT_MAX, limit))
    if raw_offset is None:
        offset = PAGE_OFFSET_DEFAULT
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer")
        offset = max(0, offset)
    return limit, offset


def paginate(items, limit, offset):
    """Slice `items` (already sorted) and build the meta pagination fields."""
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + len(page)) < total
    meta_fields = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": has_more,
    }
    return page, meta_fields


def paginated_entities(items, serializer):
    """Sort entities by created_at ascending (PRD 2.3 default; insertion order
    breaks ties), paginate, and serialize the page."""
    limit, offset = pagination_params()
    ordered = sorted(items, key=lambda e: (e["created_at"], e.get("_seq", 0)))
    page, meta_fields = paginate(ordered, limit, offset)
    return success_list([serializer(e) for e in page], meta_fields)


# ---------------------------------------------------------------------------
# Request body helpers (PRD 2.7 priority 5)
# ---------------------------------------------------------------------------
def body():
    """Return the JSON request body as a dict; anything else is a 400."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return data


def require_fields(data, *names):
    for name in names:
        if name not in data or data[name] is None:
            raise ApiError("ERR_INVALID_REQUEST", "missing required field: %s" % name)


def require_string(data, name):
    value = data.get(name)
    if not isinstance(value, str) or value == "":
        raise ApiError("ERR_INVALID_REQUEST", "field must be a non-empty string: %s" % name)
    return value


def optional_string(data, name):
    value = data.get(name)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "field must be a string: %s" % name)
    return value


def require_enum(data, name, allowed):
    value = data.get(name)
    if not isinstance(value, str) or value not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", "field %s must be one of %s" % (name, sorted(allowed)))
    return value


def require_int(data, name, minimum=None):
    value = data.get(name)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ApiError("ERR_INVALID_REQUEST", "field must be an integer: %s" % name)
    if minimum is not None and value < minimum:
        raise ApiError("ERR_INVALID_REQUEST", "field %s must be >= %d" % (name, minimum))
    return value


def optional_int(data, name, minimum=None):
    if name not in data or data[name] is None:
        return None
    return require_int(data, name, minimum)


def require_datetime(data, name):
    value = data.get(name)
    if not isinstance(value, str):
        raise ApiError("ERR_INVALID_REQUEST", "field must be an ISO 8601 string: %s" % name)
    try:
        return db.parse_iso(value)
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "field %s is not a valid ISO 8601 datetime" % name)


def require_string_list(data, name):
    value = data.get(name)
    if not isinstance(value, list) or any(not isinstance(v, str) for v in value):
        raise ApiError("ERR_INVALID_REQUEST", "field must be an array of strings: %s" % name)
    return value
