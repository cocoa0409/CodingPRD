"""Authentication and role-based access control (PRD §2.1).

Every request must carry ``X-User-ID`` (the calling operator) and
``X-User-Role`` (the capacity they act in).  A request missing either header, or
naming a role outside the recognized set, is rejected with ERR_UNAUTHENTICATED
(401).  A recognized role that is not authorized for the addressed operation is
rejected with ERR_UNAUTHORIZED (403).
"""

from flask import request

from errors import (
    ApiError,
    ERR_UNAUTHENTICATED,
    ERR_UNAUTHORIZED,
    STATUS,
)

ROLES = (
    "PlatformAdmin",
    "ReleaseManager",
    "EnvironmentAdmin",
    "StorageArchivist",
    "SecurityAuditor",
    "AppDeveloper",
)

# Every read operation across the platform is available to all six roles.
ANY_ROLE = ROLES


def _header(name):
    value = request.headers.get(name)
    if value is None:
        return None
    value = value.strip()
    return value if value else None


def current_actor():
    """Resolve the acting operator, or raise ERR_UNAUTHENTICATED."""
    user_id = _header("X-User-ID")
    role = _header("X-User-Role")
    if user_id is None or role is None or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            "X-User-ID and X-User-Role headers are required and X-User-Role must "
            "name a recognized role.",
            STATUS[ERR_UNAUTHENTICATED],
        )
    return {"user_id": user_id, "role": role}


def require_role(actor, allowed):
    """Check the acting role is listed among the operation's roles."""
    if actor["role"] not in allowed:
        raise ApiError(
            ERR_UNAUTHORIZED,
            "The acting role '%s' is not authorized for this operation." % actor["role"],
            STATUS[ERR_UNAUTHORIZED],
        )


def require(*allowed):
    """Resolve the actor and authorize them for this operation, in order."""
    actor = current_actor()
    require_role(actor, set(allowed))
    return actor