"""Auth header extraction and role authorization (cascade priorities 2 and 3)."""

from flask import request

from .constants import HEADER_USER_ID, HEADER_USER_ROLE
from .errors import (
    ERR_MISSING_AUTH_HEADERS,
    ERR_UNAUTHORIZED_ROLE,
    ApiError,
)


def require_role(roles):
    """Validate the two identity headers and the caller's role.

    Returns (role, user_id). Raises ERR_MISSING_AUTH_HEADERS when either
    header is absent and ERR_UNAUTHORIZED_ROLE when the role is not listed.
    """
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if not user_id or not user_id.strip() or not role or not role.strip():
        raise ApiError(
            ERR_MISSING_AUTH_HEADERS,
            "Both %s and %s headers are required." % (HEADER_USER_ID, HEADER_USER_ROLE),
        )
    role = role.strip()
    if role not in roles:
        raise ApiError(
            ERR_UNAUTHORIZED_ROLE,
            "Role '%s' is not authorized for this operation." % role,
        )
    return role, user_id.strip()
