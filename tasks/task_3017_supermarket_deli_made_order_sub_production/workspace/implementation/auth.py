"""Header extraction and role-based access control (PRD 2.1, SCAFFOLD Table 7).

Every request carries ``X-User-ID`` and ``X-User-Role``.  A missing header or an
unknown role is ``ERR_UNAUTHENTICATED``; a known role that is not on the
endpoint's role list is ``ERR_UNAUTHORIZED``.  Role lists come from the
endpoint table, optionally intersected with the installation's replaced
permission list, which is the supported way to force a role's denial path.
"""
import re

from errors import fail
from util import new_id

KNOWN_ROLES = (
    "PlatformAdmin",
    "DeliManager",
    "DeliClerk",
    "BakeryCoordinator",
    "ScaleOperator",
)

ENTITY_BACKED_ROLES = ("DeliManager", "DeliClerk", "BakeryCoordinator")

# Wildcards accepted in a replacement permission list in place of a path.
ROLE_WILDCARDS = {
    "PlatformAdmin": "*",
    "DeliManager": "/deli/*",
    "DeliClerk": "/deli/*",
    "BakeryCoordinator": "/deli/*",
    "ScaleOperator": "/deli/*",
}


class Actor(object):
    def __init__(self, user_id, role):
        self.id = user_id
        self.role = role

    @property
    def entity_backed(self):
        return self.role in ENTITY_BACKED_ROLES


def derive_actor(getter, store):
    """Resolve the acting identity, or raise the auth errors in priority order."""
    user_id = getter("X-User-ID")
    role = getter("X-User-Role")
    if not user_id or not role or role not in KNOWN_ROLES:
        fail("ERR_UNAUTHENTICATED")
    return Actor(user_id or new_id(), role)


def authorize(actor, allowed_roles, permissions=None, path=None):
    if actor.role not in allowed_roles:
        fail("ERR_UNAUTHORIZED")
    if permissions and path is not None:
        granted = permissions.get(actor.role)
        if granted is not None:
            if not _permitted(granted, path, actor.role):
                fail("ERR_UNAUTHORIZED")


COLLECTION_NOUNS = {
    "stores", "items", "associates", "certifications", "production-batches",
    "slicers", "sanitation-cycles", "sub-tickets", "promotions",
    "bread-supply-orders", "price-files", "labels", "catering-orders",
    "waste-records", "sub-queue", "posture-report", "role-permissions",
    "current_utc", "active-price-file", "posture-gate", "run-production-day",
    "simulate",
}


def _operations(path, method):
    """The operation tokens a replaced permission list may name for this call.

    PRD §2.1 lets an administrator replace a role's permissions and says a set
    which "omits an operation" forces that role's denial path. The operation is
    the path's final segment: a state-transition endpoint is named by its action
    verb (`ticket`, `suspend`, `activate`), a collection read or write by the
    resource noun plus the method's own verb.
    """
    segments = [seg for seg in path.strip("/").split("/") if seg]
    if not segments:
        return set()
    last = segments[-1]
    if method.upper() in ("GET", "HEAD"):
        return {last, "read"}
    if method.upper() == "POST":
        if last in COLLECTION_NOUNS:
            return {last, "create", "ticket"}
        return {last}
    if method.upper() in ("PATCH", "PUT"):
        return {last, "update"}
    return {last, "update", "delete"}


def _permitted(granted, path, role):
    """True when the replaced permission list names this operation."""
    if not granted:
        return False
    allowed = _operations(path, request_method())
    wildcard = ROLE_WILDCARDS.get(role, "*")
    for entry in granted:
        if entry == "*" or entry == wildcard:
            return True
        if entry in allowed:
            return True
        if entry.endswith("*") and path.startswith(entry[:-1]):
            return True
    return False


def request_method():
    from flask import request
    return request.method


def require_associate(actor, store):
    """Entity-backed roles must name a real Associate row (PRD 2.1)."""
    from errors import ApiError
    associate = store.associates.get(actor.id)
    if associate is None:
        raise ApiError("ERR_UNAUTHENTICATED", 401,
                       "X-User-ID must name an existing Associate for this role.")
    return associate