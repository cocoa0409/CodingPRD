"""Auth middleware (PRD section 2.1).

Every request carries X-User-ID and X-User-Role. Missing/malformed ->
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400). Valid role without
permission -> ERR_FORBIDDEN_FOR_ROLE (403).
"""
from functools import wraps

from flask import g, request

from errors import (
    ApiError,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
)

VALID_ROLES = (
    "PlatformAdmin",
    "ListingAgent",
    "Homeowner",
    "Vendor",
    "ProgramUnderwriter",
    "Any",
)


def user_context():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not user_id.strip() or role is None or role not in VALID_ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must be present and valid",
            400,
        )
    return user_id.strip(), role


def require_roles(*allowed):
    """Endpoint role gate. "Any" means any authenticated role may call."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = user_context()
            if "Any" not in allowed and role not in allowed:
                raise ApiError(
                    ERR_FORBIDDEN_FOR_ROLE,
                    "Caller role is not allowed for this endpoint",
                    403,
                )
            g.user_id = uid
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def enforce_vendor_ownership(vendor_id):
    """PRD 2.1: when the role is Vendor, X-User-ID is the acting Vendor's id
    and is compared against the resource's vendor foreign key."""
    if g.user_role == "Vendor" and g.user_id != vendor_id:
        raise ApiError(
            ERR_FORBIDDEN_FOR_ROLE,
            "Vendor identity does not match the resource vendor",
            403,
        )
