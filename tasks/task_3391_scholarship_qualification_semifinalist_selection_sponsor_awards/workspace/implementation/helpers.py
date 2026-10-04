"""Response envelope, auth/role checks, pagination, and field validation.

Envelope shape is exactly PRD section 2.2 / SCAFFOLD response_envelope:
success: { meta: {api_request_id, api_request_timestamp, [pagination]},
           response_type: "object"|"array", data: ... }
error:   { meta: {api_request_id, api_request_timestamp},
           response_type: "error", data: {error_id, message} }
"""

import re
import uuid
from datetime import date
from functools import wraps

from flask import g, jsonify, request

import constants as C
from errors import err
from store import iso_ts, parse_dt, wall_now

_INT_RE = re.compile(r"^-?\d+$")


# --------------------------------------------------------------------------
# Response envelope
# --------------------------------------------------------------------------

def make_meta(pagination=None):
    meta = {
        "api_request_id": "req_" + uuid.uuid4().hex[:24],
        "api_request_timestamp": iso_ts(wall_now()),
    }
    if pagination:
        meta.update(pagination)
    return meta


def resp_object(data, code=200):
    return jsonify({"meta": make_meta(), "response_type": "object", "data": data}), code


def resp_list(items, total, limit, offset):
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(items) < total,
    }
    return (
        jsonify(
            {"meta": make_meta(pagination), "response_type": "array", "data": items}
        ),
        200,
    )


def error_body(error_id, message):
    return {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


# --------------------------------------------------------------------------
# Auth (validation priority 1-2)
# --------------------------------------------------------------------------

def auth_before_request():
    """ERR_UNAUTHENTICATED before anything else, even before path resolution."""
    if not request.path.startswith("/api/"):
        return None
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or role not in C.ALL_ROLES or not uid:
        err("ERR_UNAUTHENTICATED", "X-User-Role or X-User-ID header missing, or role not declared")
    g.user_role = role
    g.user_id = uid
    return None


def require_roles(*roles):
    """ERR_FORBIDDEN_ROLE when the declared role is not listed for the endpoint."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if g.user_role not in roles:
                err("ERR_FORBIDDEN_ROLE", "role %s is not authorized for this endpoint" % g.user_role)
            return fn(*args, **kwargs)

        return wrapper

    return deco


# --------------------------------------------------------------------------
# Request body and field-shape validation (validation priority 10)
# --------------------------------------------------------------------------

def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def bad(msg):
    err("ERR_INVALID_REQUEST", msg)


def require_present(b, *names):
    for n in names:
        if n not in b or b[n] is None:
            bad("missing required field: %s" % n)


def check_int_field(b, name, minimum=None, maximum=None):
    if not is_int(b.get(name)):
        bad("field %s must be an integer" % name)
    if minimum is not None and b[name] < minimum:
        bad("field %s is below its minimum" % name)
    if maximum is not None and b[name] > maximum:
        bad("field %s exceeds its maximum" % name)


def check_num_field(b, name, minimum=None, maximum=None):
    if not is_num(b.get(name)):
        bad("field %s must be a number" % name)
    if minimum is not None and b[name] < minimum:
        bad("field %s is below its minimum" % name)
    if maximum is not None and b[name] > maximum:
        bad("field %s exceeds its maximum" % name)


def check_enum_field(b, name, allowed):
    if b.get(name) not in allowed:
        bad("field %s must be one of %s" % (name, ", ".join(allowed)))


def check_datetime_field(b, name):
    try:
        parse_dt(b.get(name))
    except (ValueError, AttributeError, TypeError):
        bad("field %s must be an ISO 8601 datetime" % name)


def check_date_string(value, name):
    try:
        if not isinstance(value, str):
            raise ValueError
        return date.fromisoformat(value.strip())
    except (ValueError, AttributeError, TypeError):
        bad("field %s must be an ISO 8601 date" % name)


# --------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10, 1..100; offset default 0
# --------------------------------------------------------------------------

def get_pagination():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = C.PAGE_DEFAULT_LIMIT
    else:
        if not _INT_RE.match(raw_limit):
            bad("limit must be an integer")
        limit = int(raw_limit)
        if limit < C.PAGE_MIN_LIMIT or limit > C.PAGE_MAX_LIMIT:
            bad("limit out of range")
    if raw_offset is None:
        offset = C.PAGE_DEFAULT_OFFSET
    else:
        if not _INT_RE.match(raw_offset):
            bad("offset must be an integer")
        offset = int(raw_offset)
        if offset < 0:
            bad("offset out of range")
    return limit, offset


def paginate(records, serializer):
    """records: pre-sorted full filtered list; returns a paged list response."""
    limit, offset = get_pagination()
    total = len(records)
    page = records[offset : offset + limit]
    return resp_list([serializer(r) for r in page], total, limit, offset)


def created_key(rec):
    """Default sort: created_at ascending; _seq breaks same-millisecond ties."""
    return (rec["created_at"], rec["_seq"])


def apply_filters(records, filters):
    """filters: list of (field, raw_query_value); equality match, absent/empty
    query values skipped. Records whose field value is None never match a
    non-empty filter value."""
    out = []
    for rec in records:
        ok = True
        for field, raw in filters:
            if raw is None or raw == "":
                continue
            val = rec.get(field)
            if val is None or str(val) != raw:
                ok = False
                break
        if ok:
            out.append(rec)
    return out
