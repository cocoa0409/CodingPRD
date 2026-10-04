"""Authentication, authorization and the entity-backed ownership rules.

PRD 2.1: every request carries X-User-ID and X-User-Role; both must be present
and the role must be one of the four declared roles, otherwise
ERR_UNAUTHENTICATED (401).  A role outside the endpoint's authorized list is
ERR_FORBIDDEN_ROLE (403), as is an entity_backed actor acting on a resource it
does not own.
"""

from flask import request

from errors import ApiError, ERR_FORBIDDEN_ROLE, ERR_UNAUTHENTICATED

ROLE_ORGANIZATION_USER = "OrganizationUser"
ROLE_PLATFORM_VERIFIER = "PlatformVerifier"
ROLE_DATA_CONSUMER = "DataConsumer"
ROLE_PLATFORM_ADMIN = "PlatformAdmin"

DECLARED_ROLES = (
    ROLE_ORGANIZATION_USER,
    ROLE_PLATFORM_VERIFIER,
    ROLE_DATA_CONSUMER,
    ROLE_PLATFORM_ADMIN,
)


class Actor(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_entity_backed(self):
        return self.role in (ROLE_ORGANIZATION_USER, ROLE_DATA_CONSUMER)

    def __repr__(self):  # pragma: no cover - debugging aid
        return "Actor(%r, %r)" % (self.user_id, self.role)


def actor():
    """Extract and validate the acting identity (priority rung 1)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in DECLARED_ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            "X-User-ID and X-User-Role must both be present and X-User-Role "
            "must name a declared role.",
        )
    return Actor(user_id, role)


def require_role(acting, allowed):
    """Priority rung 2: the acting role must appear in the endpoint's list."""
    if acting.role not in allowed:
        raise ApiError(
            ERR_FORBIDDEN_ROLE,
            "Role %s is not authorized for this operation." % acting.role,
        )


def require_owner(acting, owner_id, what="resource"):
    """An entity_backed actor may act only on its own organization's rows."""
    if acting.is_entity_backed and acting.user_id != owner_id:
        raise ApiError(
            ERR_FORBIDDEN_ROLE,
            "An %s may act only on its own %s." % (acting.role, what),
        )


def owner_matches(acting, owner_id):
    return (not acting.is_entity_backed) or acting.user_id == owner_id


def is_privileged(acting):
    return acting.role in (ROLE_PLATFORM_ADMIN, ROLE_PLATFORM_VERIFIER)
