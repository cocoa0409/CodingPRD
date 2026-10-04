"""Auth: header extraction and role checking."""

from flask import request

from errors import err


ROLES = {"NetworkArchitect", "RFEngineer", "SpectrumCoordinator", "SpectrumRegulator", "FieldTechnician"}


def require_roles(*allowed):
    """Validate X-User-ID / X-User-Role headers; returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid authentication headers")
    if allowed and role not in allowed:
        raise err("ERR_UNAUTHORIZED", "Role not permitted for this endpoint")
    return uid, role
