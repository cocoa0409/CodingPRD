"""Auth middleware: X-User-ID / X-User-Role header extraction and role checking.

Per PRD section 2.1:
- Both X-User-ID and X-User-Role must be present and the role recognized,
  otherwise ERR_UNAUTHENTICATED (401).
- Recognized roles: Anonymous, VolunteerEditor, Administrator,
  FundraisingManager, PaymentProcessor, GrantAdministrator, GrantReviewer,
  LegalCounsel, PlatformAdmin.
- If role is recognized but not permitted for the operation:
  ERR_UNAUTHORIZED (403).
"""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED


VALID_ROLES = {
    "Anonymous",
    "VolunteerEditor",
    "Administrator",
    "FundraisingManager",
    "PaymentProcessor",
    "GrantAdministrator",
    "GrantReviewer",
    "LegalCounsel",
    "PlatformAdmin",
}


def get_auth():
    """Return (user_id, role). Raises ApiError 401 if headers missing/invalid."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in VALID_ROLES:
        raise ApiError(ERR_UNAUTHENTICATED,
                       "Missing or invalid X-User-Role header", 401)
    if not user_id:
        raise ApiError(ERR_UNAUTHENTICATED,
                       "Missing X-User-ID header", 401)
    return user_id, role


def require_roles(*allowed):
    """Validate auth headers and that the role is in the allowed set.

    Returns (user_id, role). Raises 401 then 403 per priority order.
    """
    user_id, role = get_auth()
    if role not in allowed:
        raise ApiError(ERR_UNAUTHORIZED,
                       "Role not permitted for this operation", 403)
    return user_id, role
