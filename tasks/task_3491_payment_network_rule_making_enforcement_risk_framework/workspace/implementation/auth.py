"""Authentication and role authorization (PRD section 2.1).

Every request must carry X-User-ID and X-User-Role; the role must be one of
the four declared roles. Endpoints additionally restrict which roles may use
them. Entity-backed ownership checks live in the endpoint handlers because
they need the target resource loaded first.
"""
from functools import wraps

from flask import g, request

from errors import fail

ROLES = ("PlatformAdmin", "ParticipantOfficer", "VotingDelegate", "Auditor")


def require_roles(*roles):
    """Authenticate the headers, then require the role to be listed."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                fail(
                    "ERR_UNAUTHENTICATED",
                    "Missing or unknown X-User-Role / X-User-ID headers",
                )
            if role not in roles:
                fail(
                    "ERR_FORBIDDEN",
                    "Role %s is not authorized for this operation" % role,
                )
            g.user_id = user_id
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
