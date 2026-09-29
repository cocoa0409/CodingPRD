"""Authentication, authorisation and ownership rungs of the validation ladder.

Rungs 1-4 (missing headers, unknown role, unknown developer identity,
unauthorised role) run before anything else touches the request.  Rung 8
(ownership) is applied by each handler once the target record is resolved.
"""
import functools

from flask import g, request

from constants import ALL_ROLES, HEADER_USER_ID, HEADER_USER_ROLE, ROLE_DEVELOPER
from db import store
from errors import ApiError


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    if value.strip() == "":
        return ""
    return value


def authorise(roles, require_headers=True):
    user_id = _header(HEADER_USER_ID)
    role = _header(HEADER_USER_ROLE)

    # rung 1 -- both headers present and non-empty
    if require_headers:
        if not user_id or not role:
            raise ApiError("ERR_MISSING_AUTH_HEADERS")
    else:
        if not user_id:
            user_id = None
        if not role:
            role = None

    # rung 2 -- the role is one of the six declared roles
    if role is not None and role not in ALL_ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")

    # rung 3 -- a Developer identity must resolve to a registered developer
    if role == ROLE_DEVELOPER and ROLE_DEVELOPER in roles:
        if user_id not in store.developers:
            raise ApiError("ERR_UNKNOWN_DEVELOPER_IDENTITY")

    # rung 4 -- the role must appear in the endpoint's authorised set
    if role is not None and role not in roles:
        raise ApiError("ERR_UNAUTHORIZED")

    g.user_id = user_id
    g.role = role
    return user_id, role


def endpoint(roles, require_headers=True):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            authorise(roles, require_headers)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def acting_role():
    return getattr(g, "role", None)


def acting_user():
    return getattr(g, "user_id", None)


def is_developer_role():
    return acting_role() == ROLE_DEVELOPER


def require_owner(owner_developer_id):
    """Rung 8 -- a Developer may only reach resources it owns."""
    if is_developer_role() and acting_user() != owner_developer_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def require_not_revoked():
    """Rung 21 -- every Developer-role write refuses a REVOKED developer."""
    if not is_developer_role():
        return
    developer = store.developers.get(acting_user())
    if developer is not None and developer["standing"] == "REVOKED":
        raise ApiError("ERR_DEVELOPER_REVOKED")


def lookup(collection, identifier, error_id):
    record = collection.get(identifier)
    if record is None:
        raise ApiError(error_id)
    return record
