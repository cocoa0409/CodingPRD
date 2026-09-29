"""Header authentication and role authorization (PRD section 2.1)."""

import functools

from flask import g, request

from errors import ApiError

ROLE_ROUTE_ENGINEER = "RouteEngineer"
ROLE_FIELD_SURVEYOR = "FieldSurveyor"
ROLE_PERMIT_COORDINATOR = "PermitCoordinator"
ROLE_AUTHORITY_REVIEWER = "AuthorityReviewer"
ROLE_POLE_OWNER = "PoleOwner"
ROLE_NETWORK_RECORDS_ADMIN = "NetworkRecordsAdmin"

ALL_ROLES = (
    ROLE_ROUTE_ENGINEER,
    ROLE_FIELD_SURVEYOR,
    ROLE_PERMIT_COORDINATOR,
    ROLE_AUTHORITY_REVIEWER,
    ROLE_POLE_OWNER,
    ROLE_NETWORK_RECORDS_ADMIN,
)

HEADER_USER_ID = "X-User-ID"
HEADER_USER_ROLE = "X-User-Role"


def authenticate():
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED")
    if user_id.strip() == "" or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def endpoint(roles):
    """Wrap a view: authenticate, then authorize against the role list.

    ``roles`` is either the tuple of every role (read operations, which all six
    roles may perform) or the operation's authorized-role list.
    """
    allowed = tuple(roles)

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED")
            g.user_id = user_id
            g.user_role = role
            return view(*args, **kwargs)

        return wrapper

    return decorator


def acting_user_id():
    return g.user_id
