"""Auth middleware: header extraction and role checking."""
from flask import request
from errors import unauthenticated, forbidden

ROLES = {
    "PlatformAdmin",
    "Underwriter",
    "EmployerAdmin",
    "PayrollProvider",
    "TaxFiler",
    "Auditor",
}


def get_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise unauthenticated()
    return user_id, role


def require_roles(*allowed):
    """Authenticate, then authorize against allowed roles.

    Returns (user_id, role).
    """
    user_id, role = get_auth()
    if role not in allowed:
        raise forbidden()
    return user_id, role
