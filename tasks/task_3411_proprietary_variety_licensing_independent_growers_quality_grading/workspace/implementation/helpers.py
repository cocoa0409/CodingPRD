"""Envelope, auth, body validation, pagination, and serialization helpers."""
from datetime import datetime, timezone
from decimal import Decimal
from functools import wraps

from flask import g, jsonify, request

import constants
import store
from errors import (
    ApiError,
    err,
    ERR_UNAUTHENTICATED,
    ERR_FORBIDDEN_ROLE,
    ERR_NOT_OWN_RESOURCE,
    ERR_INVALID_REQUEST,
)


# ---------------------------------------------------------------------------
# Response envelope (SCAFFOLD section 1.0 / PRD 2.2)
# ---------------------------------------------------------------------------

def success(data, code=200, pagination=None):
    meta = {
        "api_request_id": store.new_req_id(),
        "api_request_timestamp": store.wall_iso(),
    }
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if isinstance(data, list) else "object",
        "data": data,
    }
    return jsonify(body), code


def error_response(e):
    body = {
        "meta": {
            "api_request_id": store.new_req_id(),
            "api_request_timestamp": store.wall_iso(),
        },
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


# ---------------------------------------------------------------------------
# Serialization: datetimes -> ISO 3dp, Decimal -> int/float
# ---------------------------------------------------------------------------

def dump_value(v):
    if isinstance(v, datetime):
        return store.iso(v)
    if isinstance(v, Decimal):
        if v == v.to_integral_value():
            return int(v)
        return float(v)
    if isinstance(v, dict):
        return {k: dump_value(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [dump_value(x) for x in v]
    return v


def dump(rec):
    return {k: dump_value(v) for k, v in rec.items()}


# ---------------------------------------------------------------------------
# Auth (PRD 2.1 / 2.8 tiers 1-3)
# ---------------------------------------------------------------------------

def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not uid or not role or role not in constants.ROLES:
                raise err(ERR_UNAUTHENTICATED, "Authentication headers missing or role unrecognized")
            if role not in roles:
                raise err(ERR_FORBIDDEN_ROLE, "Role not permitted for this endpoint")
            g.uid = uid
            g.role = role
            return fn(*args, **kwargs)
        return wrapper
    return deco


def check_owner(grower_id):
    """GrowerPrincipal's X-User-ID must equal the owning grower id (tier 3)."""
    if g.role == "GrowerPrincipal" and g.uid != grower_id:
        raise err(ERR_NOT_OWN_RESOURCE, "GrowerPrincipal does not own this resource chain")


# ---------------------------------------------------------------------------
# Body field validation (PRD 2.8 tier 5 -> ERR_INVALID_REQUEST)
# ---------------------------------------------------------------------------

def body():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def _bad(msg):
    raise err(ERR_INVALID_REQUEST, msg)


def req_field(b, name):
    if name not in b or b[name] is None:
        _bad("Missing required field: %s" % name)
    return b[name]


def opt_field(b, name, default=None):
    v = b.get(name, default)
    return default if v is None else v


def as_str(v, name):
    if not isinstance(v, str) or not v:
        _bad("Field %s must be a non-empty string" % name)
    return v


def as_int(v, name, min_value=None):
    if isinstance(v, bool) or not isinstance(v, int):
        _bad("Field %s must be an integer" % name)
    if min_value is not None and v < min_value:
        _bad("Field %s must be >= %s" % (name, min_value))
    return v


def as_pos_int(v, name):
    return as_int(v, name, min_value=1)


def as_num(v, name):
    """JSON number -> Decimal (exact via str)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        _bad("Field %s must be a number" % name)
    return Decimal(str(v))


def as_bool(v, name):
    if not isinstance(v, bool):
        _bad("Field %s must be a boolean" % name)
    return v


def as_enum(v, name, allowed):
    if not isinstance(v, str) or v not in allowed:
        _bad("Field %s must be one of %s" % (name, ", ".join(allowed)))
    return v


def as_str_list(v, name, allowed=None, non_empty=False):
    if not isinstance(v, list) or (non_empty and not v):
        _bad("Field %s must be a %sarray of strings" % (name, "non-empty " if non_empty else ""))
    for item in v:
        if not isinstance(item, str):
            _bad("Field %s must contain only strings" % name)
        if allowed is not None and item not in allowed:
            _bad("Field %s has an invalid member: %s" % (name, item))
    return list(v)


def as_dt(v, name):
    """Parse an ISO 8601 instant; naive values are read as UTC."""
    if not isinstance(v, str):
        _bad("Field %s must be an ISO 8601 timestamp" % name)
    s = v.strip()
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        _bad("Field %s must be an ISO 8601 timestamp" % name)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def reject_future(dt, name):
    if dt > store.clock_now():
        _bad("Field %s must not be in the future of the logical clock" % name)


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit/offset in meta of list responses
# ---------------------------------------------------------------------------

def paginate(items):
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is None:
        limit = constants.PAGE_LIMIT_DEFAULT
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            _bad("limit must be an integer")
        if isinstance(limit, bool) or limit < constants.PAGE_LIMIT_MIN or limit > constants.PAGE_LIMIT_MAX:
            _bad("limit out of range")
    if raw_offset is None:
        offset = constants.PAGE_OFFSET_DEFAULT
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            _bad("offset must be an integer")
        if offset < 0:
            _bad("offset out of range")
    items = sorted(items, key=lambda r: (r["created_at"], r["id"]))
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return [dump(r) for r in page], pagination
