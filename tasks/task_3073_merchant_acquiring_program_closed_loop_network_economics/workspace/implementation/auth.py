"""Role-based access control (PRD §2.1 and the RBAC matrix).

Nine roles exist.  Seven are operator roles with an opaque identity that the
server never compares to any row's id; two are entity-backed and carry the id of
the acting row.
"""

from errors import ERR_FORBIDDEN, ERR_UNAUTHENTICATED, ApiError

OPERATOR_ROLES = (
    "NetworkAcquirer",
    "NetworkSettlementOps",
    "NetworkCompliance",
    "NetworkDataSteward",
    "NetworkDisputeOps",
    "NetworkService",
    "NetworkIssuer",
)

ENTITY_ROLES = ("Merchant", "CardMember")

ALL_ROLES = OPERATOR_ROLES + ENTITY_ROLES

ENTITY_ROLE_TABLE = {
    "Merchant": "merchants",
    "CardMember": "cardmembers",
}


def identity_header(headers):
    value = headers.get("X-User-ID")
    if value is None:
        return None
    value = value.strip()
    return value or None


def role_header(headers):
    value = headers.get("X-User-Role")
    if value is None:
        return None
    value = value.strip()
    return value or None


class Caller:
    def __init__(self, role, user_id, is_operator):
        self.role = role
        self.user_id = user_id
        self.is_operator = is_operator

    @property
    def entity_table(self):
        return ENTITY_ROLE_TABLE.get(self.role)


def authenticate(store, headers):
    """Priority 1.  Raises ERR_UNAUTHENTICATED before any other consideration.

    The 401 is raised for exactly three conditions -- a missing X-User-Role, a
    role name that is not one of the nine declared roles, and an entity-backed
    role presented without an X-User-ID.  A present-but-unresolved identifier is
    not an authentication failure: it simply never matches an ownership
    comparison, so the caller falls through to the forbidden check instead.
    """
    del store
    role = role_header(headers)
    if role is None or role not in ALL_ROLES:
        raise ApiError(ERR_UNAUTHENTICATED)
    user_id = identity_header(headers)
    if role in ENTITY_ROLES and user_id is None:
        raise ApiError(ERR_UNAUTHENTICATED)
    return Caller(role, user_id, role in OPERATOR_ROLES)


def require_role(caller, allowed):
    """Priority 2.  Raises ERR_FORBIDDEN when the role may not act."""
    if caller.role not in allowed:
        raise ApiError(ERR_FORBIDDEN)
    return caller


def require_owned_by_caller(caller, owner_id):
    """Priority 2.  The entity-backed ownership condition.

    An entity-backed caller addressing a resource that belongs to a different
    party receives ERR_FORBIDDEN, not a not-found error.
    """
    if caller.is_operator:
        return
    if caller.user_id != owner_id:
        raise ApiError(ERR_FORBIDDEN)