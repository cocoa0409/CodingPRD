"""Auth header extraction and role checking per PRD §2.1.

Every request must carry X-User-ID and X-User-Role. Recognized roles are
exactly the seven spelled in the PRD. Auth runs before existence, state, or
business checks.
"""

import functools

from flask import request

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {
    "PlatformAdmin",
    "ProgramManager",
    "Inspector",
    "MedicalDirector",
    "Responder",
    "System",
    "Anonymous",
}


def auth_context():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED,
                  "Missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def require_roles(*allowed):
    """Decorator: authenticate, then authorize role for the endpoint."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = auth_context()
            if role not in allowed:
                raise_err(ERR_FORBIDDEN,
                          f"Role {role} is not authorized for this endpoint")
            return fn(*args, **kwargs)
        return wrapper
    return decorator
