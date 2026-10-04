"""Authentication and role gating (PRD 2.1 / 2.12).

Authentication is evaluated first, authorization second, so a request that is
both unauthenticated and unauthorized reports ERR_MISSING_USER_CONTEXT.
"""

from functools import wraps

from flask import request

import errors as E
from services import common

ROLES = {
    "IntakeAssociate",
    "Piercer",
    "StoreManager",
    "ComplianceOfficer",
    "SterilizationTechnician",
    "Customer",
    "Anonymous",
    "AnyAuthenticated",
}


def caller_context():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id == "" or role == "":
        E.fail(E.ERR_MISSING_USER_CONTEXT,
               "X-User-ID and X-User-Role headers are required")
    if role not in ROLES:
        E.fail(E.ERR_MISSING_USER_CONTEXT,
               "X-User-Role must name one of the recognized roles")
    return user_id, role


def authenticated(*allowed_roles):
    """Declare the roles permitted for an endpoint.

    AnyAuthenticated (or listing it) admits every caller presenting a valid
    role header, which is the read-only operational surface of PRD 2.1.
    """
    permitted = set(allowed_roles)

    def decorator(handler):
        @wraps(handler)
        def wrapper(*args, **kwargs):
            user_id, role = caller_context()
            allowed = "AnyAuthenticated" in permitted or role in permitted
            if not allowed:
                E.fail(E.ERR_UNAUTHORIZED_ROLE,
                       "Role %s is not permitted for this operation" % role)
            request.environ["piercing.user_id"] = user_id
            request.environ["piercing.role"] = role
            common.sweep_clock_driven_transitions()
            return handler(*args, **kwargs)
        return wrapper
    return decorator


def acting_user_id():
    return request.environ.get("piercing.user_id")


def acting_role():
    return request.environ.get("piercing.role")