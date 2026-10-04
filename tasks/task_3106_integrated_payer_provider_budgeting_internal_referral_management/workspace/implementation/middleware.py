"""Auth middleware.

PRD 2.1: every request carries X-User-ID and X-User-Role. A missing or
unrecognised value is ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER (400); a
well-formed request whose role does not hold the operation is
ERR_INSUFFICIENT_PERMISSIONS (403).
"""

from constants import ALL_ROLES, ROLE_PROVIDER
from errors import (
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
    raise_error,
)


class Principal(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_provider(self):
        return self.role == ROLE_PROVIDER


def principal_from_headers(headers):
    """Extract and validate the acting principal from the request headers."""
    user_id = headers.get("X-User-ID")
    role = headers.get("X-User-Role")
    if user_id is None or role is None:
        raise_error(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    if not str(user_id).strip() or not str(role).strip():
        raise_error(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    if role not in ALL_ROLES:
        raise_error(ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)
    return Principal(str(user_id).strip(), role)


def require_role(principal, allowed_roles):
    if principal.role not in allowed_roles:
        raise_error(ERR_INSUFFICIENT_PERMISSIONS)
    return principal