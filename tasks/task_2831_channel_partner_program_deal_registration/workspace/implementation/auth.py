"""Identity headers and RBAC (PRD 2.1, order of rejection steps 1 and 2)."""
from functools import wraps

from flask import g, request

from constants import ROLES
from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def authenticate():
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or user_id == "" or role is None or role == "":
        raise ApiError("ERR_UNAUTHENTICATED",
                       "Both identity headers are required.")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Unknown role '%s'." % role)
    g.user_id = user_id
    g.role = role
    return user_id, role


def authorize(allowed_roles):
    if g.role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role '%s' may not perform this operation." % g.role)


def endpoint(*allowed_roles):
    """Auth (401) then authorisation (403), ahead of every other check."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            authorize(allowed_roles)
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def acting_partner_scope(partner_id):
    """PRD 2.1: ownership check on the eight guarded write operations."""
    if g.role == "Partner" and g.user_id != partner_id:
        raise ApiError("ERR_PARTNER_SCOPE_VIOLATION",
                       "The acting partner does not own this resource.")
