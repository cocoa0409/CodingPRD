"""Auth middleware.

PRD 2.1: every request carries X-User-ID and X-User-Role. A request whose
X-User-Role is absent or does not name one of the three declared roles is
rejected with ERR_UNAUTHENTICATED (401); a known role that is not permitted for
the operation is rejected with ERR_UNAUTHORIZED (403).

Validation precedence (PRD 2.12): authentication first, then authorization,
then existence. The role check therefore happens before any path identifier is
resolved.
"""

from flask import request

from errors import api_error, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

PLATFORM_ADMIN = "PlatformAdmin"
CLEARING_MEMBER = "ClearingMember"
RISK_OFFICER = "RiskOfficer"

ROLES = (PLATFORM_ADMIN, CLEARING_MEMBER, RISK_OFFICER)

# All requests create the acting context; endpoints that share an operation
# across roles declare every permitted role instead of the RBAC matrix's
# "exclusive/shared" split.
ALL_ROLES = ROLES


def acting_role():
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise api_error(ERR_UNAUTHENTICATED)
    return role


def acting_user_id():
    return request.headers.get("X-User-ID")


def authenticate(permitted_roles):
    """Resolve the acting role and enforce the per-operation role list."""
    role = acting_role()
    if role not in permitted_roles:
        raise api_error(ERR_UNAUTHORIZED)
    return role


class ActingUser:
    """The resolved acting principal for one request."""

    __slots__ = ("role", "user_id")

    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id

    @property
    def is_member(self):
        return self.role == CLEARING_MEMBER

    def owns_participant(self, participant_id):
        """A ClearingMember's X-User-ID is the id of the Participant it acts as."""
        return self.role == CLEARING_MEMBER and self.user_id == participant_id


def principal(permitted_roles):
    role = authenticate(permitted_roles)
    return ActingUser(role, acting_user_id())