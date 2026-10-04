"""Request helpers shared by every route: RBAC guards, OCC staleness checks
and response-object assembly."""

from flask import g, request

from core import (
    ROLES,
    USER_ID_HEADER,
    USER_ROLE_HEADER,
    ApiError,
    fmt,
    now,
    fail,
)
from envelope import array_response, object_response, error_body, ok
from serialize import serialize

# Endpoints that skip the header requirement entirely.
NO_AUTH_ENDPOINTS = {
    "GET /wellness/subscription-tiers",
    "GET /wellness/subscription-tiers/{id}",
}

OPERATOR_ENDPOINTS = {
    "POST /_clock/set_current_utc",
    "POST /_inject/client-history",
    "POST /_inject/client-entitlement",
}

ANONYMOUS_OK = "Anonymous"


def context():
    header_id = request.headers.get(USER_ID_HEADER)
    header_role = request.headers.get(USER_ROLE_HEADER)
    if not header_id or header_role not in ROLES:
        fail("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    return header_id, header_role


def require_roles(*roles):
    """Priority 1 then priority 2 from §1.4."""
    actor_id, role = context()
    if role not in roles:
        fail("ERR_UNAUTHORIZED_ROLE")
    g.actor_id = actor_id
    g.actor_role = role
    return actor_id, role


def require_roles_or_anonymous(*roles):
    header_id = request.headers.get(USER_ID_HEADER)
    header_role = request.headers.get(USER_ROLE_HEADER)
    if not header_id and not header_role:
        g.actor_id = None
        g.actor_role = "Anonymous"
        return None, "Anonymous"
    return require_roles(*(roles if "Anonymous" in roles else roles + ("Anonymous",)))


def require_operator():
    return require_roles("OperatorOnly")


def body():
    return request.get_json(silent=True) or {}


def occ(parent, field):
    """Stale-observation precondition: when the expectation field is supplied it
    must match the row's current version (§1.4 priority 9)."""
    supplied = body().get(field)
    if supplied is None:
        return
    try:
        supplied = int(supplied)
    except (TypeError, ValueError):
        fail("ERR_STALE_VERSION")
    if supplied != parent.get("version"):
        fail("ERR_STALE_VERSION")


def ok_object(entity, status=200):
    return object_response(serialize(entity), status=status)


def ok_array(items, limit, offset, extra_meta=None):
    return array_response([serialize(i) for i in items], limit, offset, extra_meta)


def ok_raw(data, status=200):
    return object_response(_scrub(data), status=status)


def _scrub(value):
    if isinstance(value, dict):
        return {
            k: _scrub(v)
            for k, v in value.items()
            if not str(k).startswith("_")
        }
    if isinstance(value, list):
        return [_scrub(v) for v in value]
    from datetime import datetime

    if isinstance(value, datetime):
        return fmt(value)
    return value


def query_args():
    return request.args


def int_arg(name, default=None):
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def str_arg(name, default=None):
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    return raw


def bool_arg(name, default=None):
    raw = request.args.get(name)
    if raw in (None, ""):
        return default
    return str(raw).lower() in ("1", "true", "yes")


def dt_arg(name):
    from core import parse_dt

    raw = request.args.get(name)
    if raw in (None, ""):
        return None
    return parse_dt(raw)