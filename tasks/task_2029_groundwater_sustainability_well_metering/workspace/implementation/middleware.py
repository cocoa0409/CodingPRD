"""Auth context extraction, role gating, request body, and pagination."""
from flask import request

from errors import err

ALL_ROLES = ("WellOwner", "WaterMaster", "EnforcementOfficer", "AppealsOfficer", "StateRegulator")


def require_roles(*roles):
    """Validation priorities 1-2: auth context, then role membership."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        raise err("ERR_MISSING_AUTH_CONTEXT",
                  "X-User-ID and X-User-Role headers are required and the role must be declared")
    if role not in roles:
        raise err("ERR_FORBIDDEN_ROLE", "Caller role is not permitted on this endpoint")
    return uid, role


def body():
    """Request JSON object; absent/malformed/non-object bodies yield {}."""
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def paginate(items):
    """limit/offset pagination per PRD §2.3 (defaults 10/0, min 1, max 100)."""
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    if limit_s is None:
        limit = 10
    else:
        try:
            limit = int(limit_s)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "limit must be an integer")
        if limit < 1:
            raise err("ERR_INVALID_REQUEST", "limit must be at least 1")
        if limit > 100:
            limit = 100
    if offset_s is None:
        offset = 0
    else:
        try:
            offset = int(offset_s)
        except (ValueError, TypeError):
            raise err("ERR_INVALID_REQUEST", "offset must be an integer")
        if offset < 0:
            raise err("ERR_INVALID_REQUEST", "offset must be non-negative")
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + len(page) < total,
    }
    return page, pagination


def sort_default(items):
    """created_at ASC; ties broken by request-arrival order (stable sort over
    the store's insertion order)."""
    return sorted(items, key=lambda e: e["created_at"])


def query_int(name):
    """Parse an optional integer query filter; ERR_INVALID_REQUEST on garbage."""
    raw = request.args.get(name)
    if raw is None:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError):
        raise err("ERR_INVALID_REQUEST", f"{name} must be an integer")
