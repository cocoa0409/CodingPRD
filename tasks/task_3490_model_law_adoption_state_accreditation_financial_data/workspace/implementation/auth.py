"""Authentication and role/ownership authorization (PRD 2.1, 2.8 stages 1-2).

Headers: X-User-ID and X-User-Role. Six declared roles. StateRegulator /
InsurerUser / ProducerUser are entity-backed: X-User-ID must name an existing
instance of that entity, else ERR_UNAUTHENTICATED (401).
"""

from flask import request

from db import store
from errors import ApiError

ROLE_ASSOCIATION_STAFF = "AssociationStaff"
ROLE_ACTUARY = "Actuary"
ROLE_STATE_REGULATOR = "StateRegulator"
ROLE_INSURER_USER = "InsurerUser"
ROLE_PRODUCER_USER = "ProducerUser"
ROLE_REVIEW_TEAM_LEAD = "ReviewTeamLead"

ALL_ROLES = frozenset({
    ROLE_ASSOCIATION_STAFF,
    ROLE_ACTUARY,
    ROLE_STATE_REGULATOR,
    ROLE_INSURER_USER,
    ROLE_PRODUCER_USER,
    ROLE_REVIEW_TEAM_LEAD,
})

_ENTITY_BACKED = {
    ROLE_STATE_REGULATOR: "states",
    ROLE_INSURER_USER: "insurers",
    ROLE_PRODUCER_USER: "producers",
}


class Principal:
    __slots__ = ("user_id", "role", "entity")

    def __init__(self, user_id, role, entity):
        self.user_id = user_id
        self.role = role
        self.entity = entity  # resolved State/Insurer/Producer record, else None


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required", 401)
    if role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Unknown role: %s" % role, 401)
    entity = None
    coll = _ENTITY_BACKED.get(role)
    if coll is not None:
        entity = getattr(store, coll).get(user_id)
        if entity is None:
            raise ApiError(
                "ERR_UNAUTHENTICATED",
                "X-User-ID does not name an existing instance for role %s" % role,
                401,
            )
    return Principal(user_id, role, entity)


def require_role(principal, allowed):
    if principal.role not in allowed:
        raise ApiError(
            "ERR_FORBIDDEN",
            "Role %s is not authorized for this endpoint" % principal.role,
            403,
        )


def forbidden(message):
    raise ApiError("ERR_FORBIDDEN", message, 403)
