"""Authentication, authorization and request plumbing (PRD 2.1)."""

import functools

from flask import request

from db import db
from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLE_PRICING_ANALYST = "PricingAnalyst"
ROLE_MERCHANDISE_DIRECTOR = "MerchandiseDirector"
ROLE_STORE_MANAGER = "StoreManager"
ROLE_VENDOR_REP = "VendorRep"
ROLE_CONTROLLER = "Controller"

ALL_ROLES = (
    ROLE_PRICING_ANALYST,
    ROLE_MERCHANDISE_DIRECTOR,
    ROLE_STORE_MANAGER,
    ROLE_VENDOR_REP,
    ROLE_CONTROLLER,
)


def authenticate():
    """Rule 1: both identity headers must be present and non-empty."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or user_id == "" or role is None or role == "":
        raise ApiError("ERR_UNAUTHENTICATED",
                       "Both %s and %s are required." %
                       (USER_ID_HEADER, USER_ROLE_HEADER))
    return user_id, role


def authorize(role, roles):
    """Rule 2: the role must be recognised and permitted for the operation."""
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHORIZED", "Unrecognised role '%s'." % role)
    if roles is not None and role not in roles:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role '%s' may not perform this operation." % role)


def body():
    """Parsed JSON request body; an absent body reads as an empty object."""
    raw = request.get_data(cache=True)
    if raw is None or len(raw.strip()) == 0:
        return {}
    try:
        parsed = request.get_json(force=True, silent=False)
    except Exception:
        raise ApiError("ERR_VALIDATION", "Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_VALIDATION", "Request body must be a JSON object.")
    return parsed


def endpoint(blueprint, rule, methods, roles):
    """Register a handler behind the auth/authorization ladder."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(**kwargs):
            with db.lock:
                user_id, role = authenticate()
                authorize(role, roles)
                return fn(user_id, role, **kwargs)

        blueprint.add_url_rule(rule, endpoint=fn.__name__, view_func=wrapper,
                               methods=methods)
        return wrapper

    return decorator
