"""Authentication, role admission, target-state ownership and entity-backed
ownership checks (PRD sections 2.1, 2.6 steps 1-3 and 6, 2.10)."""
from flask import request

from errors import ApiError
from store import db

ROLE_CARE_MANAGER = "CareManager"
ROLE_SUPERVISOR = "PracticeSupervisor"
ROLE_FAMILY = "FamilyDecisionMaker"
ROLE_BILLING = "BillingAdministrator"
ROLE_ADMIN = "PracticeAdmin"

ROLES = (ROLE_CARE_MANAGER, ROLE_SUPERVISOR, ROLE_FAMILY, ROLE_BILLING,
         ROLE_ADMIN)

ALL_ROLES = ROLES


class Actor(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_family(self):
        return self.role == ROLE_FAMILY


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED",
                       "The X-User-ID header is missing or empty.")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED",
                       "The X-User-Role header is missing or empty.")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED",
                       "The X-User-Role header does not name a declared role.")
    return Actor(user_id, role)


def actor_for(*roles):
    """Ladder steps 1 and 2: authenticate, then admit the role."""
    actor = authenticate()
    if actor.role not in roles:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Role %s may not call this operation." % actor.role)
    return actor


def owns_target(actor, ownership, target):
    """Ladder step 3: on a multi-role operation the acting role must own the
    specific target state or action it is requesting."""
    if target is None:
        return
    owner = ownership.get(target)
    if owner is None:
        return
    if actor.role not in owner:
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "Role %s does not own the requested outcome %s." % (actor.role, target))


def deny_unowned(actor, ownership, target):
    """Reject a target state that no role owns at all."""
    if target in ownership:
        return
    raise ApiError("ERR_UNAUTHORIZED",
                   "No role may request the outcome %s directly." % target)


def resolve_supervisor(actor):
    """Ladder step 6: an X-User-ID presenting PracticeSupervisor must resolve to
    an existing CareManager whose is_supervisor is true."""
    if actor.role != ROLE_SUPERVISOR:
        return None
    care_manager = db.care_managers.get(actor.user_id)
    if care_manager is None or not care_manager.get("is_supervisor"):
        raise ApiError(
            "ERR_UNAUTHORIZED",
            "The acting X-User-ID does not resolve to a supervising care manager.")
    return care_manager


def resolve_contact(actor):
    """A FamilyDecisionMaker's X-User-ID must resolve to a FamilyContact."""
    contact = db.contacts.get(actor.user_id)
    if contact is None:
        raise ApiError("ERR_UNAUTHORIZED",
                       "The acting X-User-ID does not resolve to a family contact.")
    return contact


def family_scope_client(actor):
    """Return the client_id a FamilyDecisionMaker is confined to, else None."""
    if not actor.is_family:
        return None
    return resolve_contact(actor)["client_id"]


def family_read_guard(actor, client_id):
    """Every read a FamilyDecisionMaker performs must resolve to its own client."""
    if not actor.is_family:
        return
    scope = resolve_contact(actor)["client_id"]
    if client_id != scope:
        raise ApiError("ERR_UNAUTHORIZED",
                       "A family decision maker may only read its own client's record.")
