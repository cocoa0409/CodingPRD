"""Auth header extraction and role checking.

Auth headers: X-User-ID and X-User-Role (scaffold §validations priority 1-2,
PRD §2.1). Roles: ProgramAdmin, OfficeManager, CaseManager, Client, Preparer,
EnrolledAgent.
"""

from flask import request

import errors

ROLES = {
    "ProgramAdmin",
    "OfficeManager",
    "CaseManager",
    "Client",
    "Preparer",
    "EnrolledAgent",
}

# Entity-backed roles: X-User-ID is the id of a persisted resource of that type.
ENTITY_BACKED_ROLES = {"Client", "Preparer", "EnrolledAgent"}


class Identity:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def get_identity():
    """Extract and validate identity headers. Raises ApiError(401)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.unauthenticated()
    return Identity(user_id, role)


def require_roles(identity, allowed):
    """Raise ApiError(403) if the identity's role is not in allowed."""
    if identity.role not in allowed:
        raise errors.forbidden()
