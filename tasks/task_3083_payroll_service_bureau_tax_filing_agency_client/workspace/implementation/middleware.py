"""Auth middleware: header extraction and role checking per PRD section 2.1 and 2.8."""

from flask import request

import errors

ROLES = {
    "ClientPayrollAdmin",
    "BureauOnboarder",
    "BureauTaxFiler",
    "BureauTreasury",
    "BureauCompliance",
}

ENTITY_BACKED_ROLES = {"ClientPayrollAdmin"}


class AuthContext:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Priority 1: X-User-Role present and declared; X-User-ID required for entity-backed roles."""
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES:
        raise errors.unauthenticated("X-User-Role header missing or not a declared role")
    user_id = request.headers.get("X-User-ID")
    if role in ENTITY_BACKED_ROLES and not user_id:
        raise errors.unauthenticated("X-User-ID required for entity-backed role")
    return AuthContext(user_id, role)


def require_roles(auth, allowed):
    """Priority 2: role must be permitted for the endpoint."""
    if auth.role not in allowed:
        raise errors.forbidden("Role not permitted for this endpoint")


def check_client_identity(auth, client_id):
    """Priority 3: entity-backed identity check for ClientPayrollAdmin."""
    if auth.role == "ClientPayrollAdmin":
        if client_id is None or auth.user_id != client_id:
            raise errors.forbidden("ClientPayrollAdmin may only act on their own client aggregate")
