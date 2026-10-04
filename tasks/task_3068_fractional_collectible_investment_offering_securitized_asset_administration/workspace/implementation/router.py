"""Route inventory + the evaluation-order dispatch core (§2.4).

The catalogue of checks is enforced in this module:
  1 credential presence (ERR_UNAUTHENTICATED)
  2 role permission (ERR_UNAUTHORIZED)
  3 investor eligibility screening
  4 existence (ERR_NOT_FOUND)
  5 jurisdiction override
  6 declared state  ...  20 sibling exclusivity
  22 route existence (ERR_ROUTE_NOT_FOUND)
  23 method allowance (ERR_METHOD_NOT_ALLOWED)
"""
from flask import request, g, make_response

from envelope import ApiError, error_response, ok, paginated, request_id
from catalog import ROLES, DEFAULT_LIMIT, MAX_LIMIT
from store import DB

# path template -> {method: (roles, handler ref name)}
ROUTES = {}


def route(path, methods):
    def deco(fn):
        ROUTES.setdefault(path, {})
        entry = {}
        for m in methods:
            entry[m] = fn
        ROUTES[path] = entry
        return fn
    return deco


def register(path, methods, handlers):
    """handlers: {method: callable}"""
    ROUTES[path] = dict(handlers)


PLACEHOLDER_NAMES = {}


def match_path(raw):
    """Match a concrete path against the declared templates.

    Returns (template, params) or (None, None)."""
    parts = [p for p in raw.split("/") if p != ""]
    for template in ROUTES:
        tparts = [p for p in template.split("/") if p != ""]
        if len(tparts) != len(parts):
            continue
        params = {}
        ok_match = True
        for tp, pp in zip(tparts, parts):
            if tp.startswith("{") and tp.endswith("}"):
                params[tp[1:-1]] = pp
            elif tp != pp:
                ok_match = False
                break
        if ok_match:
            return template, params
    return None, None


def read_limit_offset():
    from flask import request as _r
    limit_raw = _r.args.get("limit")
    offset_raw = _r.args.get("offset")
    try:
        limit = int(limit_raw) if limit_raw not in (None, "") else DEFAULT_LIMIT
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "limit must be an integer.")
    try:
        offset = int(offset_raw) if offset_raw not in (None, "") else 0
    except (TypeError, ValueError):
        raise ApiError("ERR_INVALID_REQUEST", "offset must be an integer.")
    if limit < 1 or limit > MAX_LIMIT:
        raise ApiError("ERR_INVALID_REQUEST",
                       "limit must be between 1 and %d." % MAX_LIMIT)
    if offset < 0:
        raise ApiError("ERR_INVALID_REQUEST", "offset must not be negative.")
    return limit, offset


def identity():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is not None:
        user_id = user_id.strip()
    if role is not None:
        role = role.strip()
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require_credentials():
    user_id, role = identity()
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-ID and X-User-Role must both be present and non-blank.")


def require_role(roles):
    user_id, role = identity()
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-ID and X-User-Role must both be present and non-blank.")
    if role not in ROLES or (roles and role not in roles):
        raise ApiError("ERR_UNAUTHORIZED",
                       "The acting role is not permitted for this operation.")