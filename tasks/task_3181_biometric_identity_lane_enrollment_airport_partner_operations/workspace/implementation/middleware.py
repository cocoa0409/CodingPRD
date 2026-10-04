"""Auth / RBAC / pagination / request-body helpers per PRD §2.1, §2.3, §2.8."""
from flask import request

from errors import ApiError

DECLARED_ROLES = {
    "Member",
    "Ambassador",
    "OpsAdmin",
    "PartnerManager",
    "ComplianceOfficer",
    "VenueOps",
}

# Which roles may access each route. Filled in by decorators at import time.
ROUTE_ROLES = {}


def require_roles(*roles):
    """Decorator: records allowed roles for the wrapped view and enforces auth+RBAC."""
    def wrap(fn):
        allowed = set(roles)
        endpoint_key = fn.__module__ + "." + fn.__name__
        ROUTE_ROLES[endpoint_key] = allowed

        def inner(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            user_role = request.headers.get("X-User-Role")
            if not user_id or not user_role or user_role not in DECLARED_ROLES:
                raise ApiError(
                    "ERR_UNAUTHENTICATED", 401,
                    "Missing X-User-ID / X-User-Role or unrecognized role",
                )
            if user_role not in allowed:
                raise ApiError(
                    "ERR_UNAUTHORIZED", 403,
                    f"Role {user_role} is not permitted on this endpoint",
                )
            request.user_id = user_id
            request.user_role = user_role
            return fn(*args, **kwargs)
        inner.__name__ = fn.__name__
        inner.__module__ = fn.__module__
        return inner
    return wrap


def body():
    """Return the parsed JSON body, or {} when empty/absent."""
    if not request.data:
        return {}
    try:
        data = request.get_json(force=True, silent=True)
    except Exception:
        data = None
    if data is None:
        raise ApiError("ERR_VALIDATION", 400, "Request body must be valid JSON")
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 400, "Request body must be a JSON object")
    return data


def require_field(data, name):
    value = data.get(name)
    if value is None:
        raise ApiError("ERR_VALIDATION", 400, f"Missing required field: {name}")
    return value


def pagination_params():
    """Parse limit/offset per PRD §2.3: default 10, min 1, max 100, offset default 0."""
    args = request.args
    try:
        limit = int(args.get("limit", 10))
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "limit must be an integer")
    try:
        offset = int(args.get("offset", 0))
    except (TypeError, ValueError):
        raise ApiError("ERR_VALIDATION", 400, "offset must be an integer")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_VALIDATION", 400, "limit must be between 1 and 100")
    if offset < 0:
        raise ApiError("ERR_VALIDATION", 400, "offset must be >= 0")
    return limit, offset


def paginate(items, limit, offset):
    """items: full sorted list. Returns (page_items, pagination_meta)."""
    total = len(items)
    page = items[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta
