"""Auth middleware: X-User-ID / X-User-Role header checks and RBAC helpers."""

from flask import request

import errors

ROLES = ("Candidate", "Employer", "PlatformAdmin")
ENTITY_BACKED = ("Candidate", "Employer")


def get_auth():
    """Return (role, user_id). Raises ApiError(ERR_UNAUTHENTICATED) on failure."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ROLES:
        raise errors.unauthenticated("X-User-Role missing or not a declared role")
    if role in ENTITY_BACKED:
        if not user_id:
            raise errors.unauthenticated("X-User-ID missing for entity-backed role")
    return role, user_id


def require_roles(*allowed):
    role, user_id = get_auth()
    if role not in allowed:
        raise errors.forbidden(f"Role {role} is not permitted for this endpoint")
    return role, user_id
