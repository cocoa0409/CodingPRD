"""Acting identities and RBAC (PRD 2.1) in the precedence order of PRD 2.12."""

from flask import request

from errors import ApiError
from store import db

ROLES = ["Reporter", "StandardsEditor", "LegalCounsel", "ExecutiveEditor", "PublicEditor"]

# Entity-backed roles: role -> (collection, attribute, required attribute value)
ENTITY_BACKED = {
    "Reporter": ("journalists", "role_title", "REPORTER"),
    "StandardsEditor": ("journalists", "role_title", "STANDARDS_EDITOR"),
    "ExecutiveEditor": ("journalists", "role_title", "EXECUTIVE_EDITOR"),
    "LegalCounsel": ("reviewers", "discipline", "LEGAL"),
}


class Actor(object):
    __slots__ = ("user_id", "role", "record")

    def __init__(self, user_id, role, record=None):
        self.user_id = user_id
        self.role = role
        self.record = record

    @property
    def is_reporter(self):
        return self.role == "Reporter"


def authenticate(bootstrap=False):
    """Steps 1 and 2 of the precedence ladder."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "X-User-ID and X-User-Role headers are required and the role must be recognized.")
    record = None
    if not bootstrap and role in ENTITY_BACKED:
        collection, attribute, expected = ENTITY_BACKED[role]
        record = getattr(db, collection).get(user_id)
        if record is None or record.get(attribute) != expected:
            raise ApiError("ERR_UNAUTHORIZED",
                           "X-User-ID does not resolve to a %s valid for role %s." % (attribute, role))
    return Actor(user_id, role, record)


def require_roles(actor, allowed):
    """Step 3 of the precedence ladder."""
    if actor.role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role %s is not authorized for this operation." % actor.role)


def auth(allowed, bootstrap=False):
    actor = authenticate(bootstrap=bootstrap)
    require_roles(actor, allowed)
    return actor


def require_ownership(actor, owner_journalist_id):
    """Step 4: Reporter ownership.  Only a Reporter is held to it (PRD 2.1)."""
    if actor.role != "Reporter":
        return
    if owner_journalist_id is None:
        return
    if actor.user_id != owner_journalist_id:
        raise ApiError("ERR_UNAUTHORIZED",
                       "A reporter may only write resources that belong to them.")


def require_not_party(actor, forbidden_ids):
    """Step 5: segregation of duties (PRD 2.10)."""
    for value in forbidden_ids:
        if value is not None and actor.user_id == value:
            raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                           "The acting user is a party to the matter being judged.")
