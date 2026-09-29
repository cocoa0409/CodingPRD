"""Authentication, endpoint authorisation, ownership and two-person control.

Rejection ladder bands 1-4 (PRD §2.9):
  1. Authentication      -> ERR_UNAUTHENTICATED (401)
  2. Endpoint authorisation -> ERR_UNAUTHORIZED (403)
  3. Resource ownership  -> ERR_NOT_RESOURCE_OWNER (403)
  4. Two-person control  -> ERR_SEGREGATION_OF_DUTIES (403)
"""
from flask import request

from constants import HEADER_USER_ID, HEADER_USER_ROLE, ROLES
from errors import fail


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_member(self):
        return self.role == "Member"


def authenticate():
    """Band 1: both headers present and non-empty, role in the enumeration."""
    user_id = request.headers.get(HEADER_USER_ID)
    role = request.headers.get(HEADER_USER_ROLE)
    if user_id is None or not str(user_id).strip():
        fail("ERR_UNAUTHENTICATED", "The %s header is missing or empty." % HEADER_USER_ID)
    if role is None or not str(role).strip():
        fail("ERR_UNAUTHENTICATED", "The %s header is missing or empty." % HEADER_USER_ROLE)
    role = str(role).strip()
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "'%s' is not a declared role." % role)
    return Caller(str(user_id).strip(), role)


def authorize(caller, allowed_roles):
    """Band 2: the acting role appears in the endpoint's authorised list."""
    if caller.role not in allowed_roles:
        fail(
            "ERR_UNAUTHORIZED",
            "Role %s is not authorised for this endpoint." % caller.role,
        )
    return caller


def guard(allowed_roles):
    """Bands 1 and 2 together; returns the Caller."""
    caller = authenticate()
    authorize(caller, allowed_roles)
    return caller


def require_owner(caller, household_id):
    """Band 3: for a Member, X-User-ID must equal the owning household id.

    Operator identities (every non-Member role) are opaque and are never
    compared against any entity id.
    """
    if caller.is_member and household_id is not None and caller.user_id != household_id:
        fail(
            "ERR_NOT_RESOURCE_OWNER",
            "This resource belongs to a different household.",
        )


def require_transition_role(caller, allowed_roles):
    """Band 2, applied per-transition where the PRD narrows the actor set for a
    specific to_status on a shared transitions endpoint."""
    if caller.role not in allowed_roles:
        fail(
            "ERR_UNAUTHORIZED",
            "Role %s may not perform this transition." % caller.role,
        )


def require_segregation(caller, raiser_user_id):
    """Band 4: the deciding user may not be the user who raised the item."""
    if raiser_user_id is not None and caller.user_id == raiser_user_id:
        fail(
            "ERR_SEGREGATION_OF_DUTIES",
            "The user who raised this item may not decide it.",
        )
