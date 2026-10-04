"""Authentication, role permission enforcement and request context (§2.1, §1.7).

Headers: `X-User-ID` (present, non-empty) and `X-User-Role` (present and equal
to one of the six declared roles). Failures are ERR_UNAUTHENTICATED (401); a
declared-but-unpermitted role, or an entity-backed actor that neither owns nor
moderates the target resource, is ERR_FORBIDDEN_ROLE (403).
"""

from flask import g, request

import db
from errors import fail

ROLES = (
    "Account",
    "Moderator",
    "PlatformAdmin",
    "Anonymous",
    "ContentReviewer",
    "SuccessionAuditor",
)

# Roles whose X-User-ID names a persisted entity.
ENTITY_BACKED = {"Account": "Account", "Moderator": "Moderator"}

# Roles that are not tied to any persisted entity: the server never compares
# their X-User-ID against an entity id.
OPAQUE_ROLES = {"PlatformAdmin", "Anonymous", "ContentReviewer", "SuccessionAuditor"}


class Actor:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_account(self):
        return self.role == "Account"

    @property
    def is_moderator(self):
        return self.role == "Moderator"

    @property
    def is_admin(self):
        return self.role == "PlatformAdmin"

    def __repr__(self):
        return f"Actor({self.role}:{self.user_id})"


def authenticate():
    """Priority 1 — the two mandatory headers and the declared role set."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role == "" or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is missing or not a declared role")
    if user_id is None or user_id.strip() == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID is missing")
    return Actor(user_id, role)


def current():
    actor = getattr(g, "actor", None)
    if actor is None:
        actor = authenticate()
        g.actor = actor
    return actor


# --------------------------------------------------------------------------
# Priority 2 — role permission and entity-backed ownership
# --------------------------------------------------------------------------
def require_roles(*allowed):
    actor = current()
    if actor.role not in allowed:
        fail("ERR_FORBIDDEN_ROLE", "the acting role is not permitted for this operation")
    return actor


def require_community_member(community_id):
    """A Moderator moderates its own community only (§2.1).

    The acting Moderator's row is identified by X-User-ID. A row that resolves
    to a different community is refused; an identifier that resolves to no row
    at all is carried as an opaque operator identifier.
    """
    actor = current()
    if actor.role != "Moderator":
        return actor
    row = db.find("Moderator", actor.user_id)
    if row is not None and row.get("community_id") != community_id:
        fail("ERR_FORBIDDEN_ROLE", "the acting moderator does not moderate this community")
    return actor


def acting_moderator_row(community_id):
    """The acting Moderator row inside `community_id`, or None."""
    actor = current()
    if actor.role != "Moderator":
        return None
    row = db.find("Moderator", actor.user_id)
    if row is None or row.get("community_id") != community_id:
        return None
    return row


def require_account_owner(account_id):
    """An Account role reaches only its own account-scoped records (§3.10)."""
    actor = current()
    if actor.role == "Account" and account_id != actor.user_id:
        fail("ERR_FORBIDDEN_ROLE", "an account may reach only its own records")
    return actor


def actor_account_id():
    actor = current()
    return actor.user_id if actor.role == "Account" else None