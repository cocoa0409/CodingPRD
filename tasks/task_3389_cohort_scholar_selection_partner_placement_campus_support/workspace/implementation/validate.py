"""Request-pipeline helpers: auth (tier 1), request shape (tier 2), role
authorization (tier 3), pagination params, and resource lookup (tiers 5/6).
"""

import re
from datetime import date

from constants import (
    PAGE_LIMIT_DEFAULT,
    PAGE_LIMIT_MAX,
    PAGE_LIMIT_MIN,
    PAGE_OFFSET_DEFAULT,
    ROLES,
)
from core import parse_iso
from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_NOT_FOUND,
    ERR_UNAUTHENTICATED,
)
from flask import request

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def auth():
    """Tier 1: X-User-Role and X-User-ID present, well-formed, declared role."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if role is None or uid is None or role not in ROLES or not uid.strip():
        raise ApiError(
            ERR_UNAUTHENTICATED,
            401,
            "Missing, malformed, or unknown-role X-User-Role / X-User-ID headers",
        )
    return uid, role


def require_role(role, allowed):
    """Tier 3: caller's role must be in the endpoint's authorized-role list."""
    if role not in allowed:
        raise ApiError(
            ERR_FORBIDDEN, 403, "Role %s is not authorized for this endpoint" % role
        )


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Request body must be a JSON object")
    return data


def req_str(d, name):
    v = d.get(name)
    if v is None or not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' is required and must be a string" % name)
    return v


def req_int(d, name):
    v = d.get(name)
    if v is None or isinstance(v, bool) or not isinstance(v, int):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' is required and must be an integer" % name)
    return v


def req_enum(d, name, values):
    v = d.get(name)
    if v is None or not isinstance(v, str) or v not in values:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "Field '%s' is required and must be one of %s" % (name, ", ".join(values)),
        )
    return v


def req_dt(d, name):
    v = d.get(name)
    if v is None or not isinstance(v, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' is required and must be an ISO8601 datetime" % name)
    try:
        return parse_iso(v)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' is not a parseable ISO8601 datetime" % name)


def req_date(d, name):
    v = d.get(name)
    if v is None or not isinstance(v, str) or not _DATE_RE.match(v):
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' is required and must be a YYYY-MM-DD date" % name)
    try:
        return date.fromisoformat(v)
    except ValueError:
        raise ApiError(ERR_INVALID_REQUEST, 400, "Field '%s' is not a valid calendar date" % name)


def lookup(collection, ident):
    """Tiers 5/6: an id segment or body reference must name an existing resource."""
    if not isinstance(ident, str) or ident not in collection:
        raise ApiError(ERR_NOT_FOUND, 404, "Resource not found: %s" % (ident,))
    return collection[ident]


def page_args():
    """Tier 2 for list endpoints: limit (default 10, 1..100), offset (default 0, >= 0)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = PAGE_LIMIT_DEFAULT
    offset = PAGE_OFFSET_DEFAULT
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be an integer")
        if limit < PAGE_LIMIT_MIN or limit > PAGE_LIMIT_MAX:
            raise ApiError(ERR_INVALID_REQUEST, 400, "limit must be between 1 and 100")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be an integer")
        if offset < 0:
            raise ApiError(ERR_INVALID_REQUEST, 400, "offset must be >= 0")
    return limit, offset


def apply_page(items, limit, offset):
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, meta
