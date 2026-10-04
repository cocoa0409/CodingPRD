"""Authentication, role resolution and ownership checks.

Header scheme is read from PRD section 2.1 and the scaffold's auth
validations[]: every request carries X-User-Role naming a declared role, and
X-User-ID.  For the entity-backed role (RatingAnalyst) X-User-ID is the id of
the acting Analyst and is compared against the analyst foreign key of the
resource being acted on.  For every other role X-User-ID is an opaque operator
identifier and is never compared to an entity id.
"""

from functools import wraps

from flask import request

from db import db
from errors import fail

ROLES = (
    "EngagementManager",
    "RatingAnalyst",
    "ComplianceOfficer",
    "CommitteeChair",
    "CompensationCommittee",
    "Anonymous",
    "PlatformAdmin",
)

# Roles whose X-User-ID is tied to a persisted Analyst row.
ENTITY_BACKED = {"RatingAnalyst"}

ANONYMOUS = "Anonymous"

ROLE_HEADER = "X-User-Role"
ID_HEADER = "X-User-ID"


class Actor(object):
    def __init__(self, role, user_id):
        self.role = role
        self.user_id = user_id

    def is_analyst(self):
        return self.role in ENTITY_BACKED

    def owns_analyst(self, analyst_id):
        """Ownership check for resources that reference an Analyst."""
        if not self.is_analyst():
            return True
        return self.user_id == analyst_id


def resolve_actor():
    """Read and validate the identity context (auth priority 1)."""
    role = request.headers.get(ROLE_HEADER)
    if role is None:
        fail("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    role = role.strip()
    if role not in ROLES:
        fail("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")

    user_id = request.headers.get(ID_HEADER)
    if user_id is not None:
        user_id = user_id.strip()
    if not user_id and role != ANONYMOUS:
        fail("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER")
    return Actor(role, user_id or "")


def permitted(actor, allowed):
    """Auth priority 2 — is this role permitted for the operation?"""
    if "Any" in allowed:
        return True
    if actor.role in allowed:
        return True
    fail("ERR_INSUFFICIENT_PERMISSIONS")


def authed(*allowed):
    """Decorator: resolve identity, enforce the role set, hand over the body."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            actor = resolve_actor()
            permitted(actor, set(allowed))
            return fn(actor, *args, **kwargs)

        return wrapper

    return decorator


def require_own_analyst(actor, analyst_id):
    """Auth priority 2 for entity-backed ownership checks."""
    if not actor.owns_analyst(analyst_id):
        fail("ERR_INSUFFICIENT_PERMISSIONS")


def analyst_exists_or_404(analyst_id):
    if analyst_id not in db.analysts:
        fail("ERR_RESOURCE_NOT_FOUND")