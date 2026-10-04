"""Header authentication, role authorization and RBAC (PRD section 2.1, section 2.14)."""
from flask import request

import core

ROLE_HEADER = "X-User-Role"
ID_HEADER = "X-User-ID"

ROLE_NAMES = (
    "PlatformAdmin",
    "ResearchAnalyst",
    "SeatUser",
    "LicensingAdmin",
    "EnforcementOfficer",
    "BrokerPublisher",
)

# presented role -> persisted User.role spelling
ENTITY_BACKED = {
    "ResearchAnalyst": "RESEARCH_ANALYST",
    "SeatUser": "SEAT_USER",
    "LicensingAdmin": "LICENSING_ADMIN",
    "EnforcementOfficer": "ENFORCEMENT_OFFICER",
    "BrokerPublisher": "BROKER_PUBLISHER",
}


class Actor:
    def __init__(self, user_id, role, user=None):
        self.user_id = user_id
        self.role = role
        self.user = user

    @property
    def organization_id(self):
        return self.user.get("organization_id") if self.user else None

    @property
    def assigned_market(self):
        return self.user.get("assigned_market") if self.user else None


def read_headers():
    """Priority 1: both headers present and non-empty, else ERR_UNAUTHENTICATED."""
    user_id = request.headers.get(ID_HEADER)
    role = request.headers.get(ROLE_HEADER)
    if user_id is None or role is None:
        raise core.ApiError("ERR_UNAUTHENTICATED")
    user_id = user_id.strip()
    role = role.strip()
    if user_id == "" or role == "":
        raise core.ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLE_NAMES:
        raise core.ApiError("ERR_UNAUTHENTICATED",
                            "%s must name one of the six recognised roles." % ROLE_HEADER)
    return user_id, role


def resolve_actor():
    """Resolve the acting principal from the headers."""
    user_id, role = read_headers()
    actor = Actor(user_id, role)
    if role in ENTITY_BACKED:
        user = core.users.get(user_id)
        if user is None:
            raise core.ApiError("ERR_UNAUTHORIZED",
                                "X-User-ID does not resolve to a user row.")
        actor.user = user
    return actor


def authorize_as(user_id, role, allowed_roles):
    """Priority 2: role permitted for the operation, and the entity-backed user active."""
    if role not in allowed_roles:
        raise core.ApiError("ERR_UNAUTHORIZED")
    actor = Actor(user_id, role)
    expected = ENTITY_BACKED.get(role)
    if expected is not None:
        user = core.users.get(user_id)
        if user is None or user.get("status") != "ACTIVE" or user.get("role") != expected:
            raise core.ApiError("ERR_UNAUTHORIZED",
                                "X-User-ID does not resolve to an active %s user." % expected)
        actor.user = user
    return actor


def authorize(allowed_roles):
    """Convenience wrapper: read the headers, then authorise."""
    user_id, role = read_headers()
    return authorize_as(user_id, role, allowed_roles)


def acting_user(actor):
    if actor.user is None:
        raise core.ApiError("ERR_UNAUTHORIZED")
    return actor.user