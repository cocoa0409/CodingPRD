"""Auth header extraction and role checking (PRD 2.1 / 2.10 steps 1-2, RBAC 1.7).

Exactly four roles are recognised: PlatformAdmin, AdvisorOps, BranchManager,
ComplianceOfficer.  X-User-Role absent or unknown -> ERR_UNAUTHENTICATED (401).
A recognised role outside the operation's grant -> ERR_UNAUTHORIZED (403).

AdvisorOps is entity_backed: X-User-ID is the id of the acting Advisor and the
ownership check compares a resource's advisor foreign-key field to X-User-ID.
"""

import flask

from errors import fail

ROLES = ("PlatformAdmin", "AdvisorOps", "BranchManager", "ComplianceOfficer")

# "Any" in the endpoint table means any authenticated role.
ANY = ROLES

# Roles whose X-User-ID is an opaque operator identifier, never an entity id.
OPAQUE_ROLES = ("PlatformAdmin", "BranchManager", "ComplianceOfficer")


def acting_role():
    role = flask.request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        fail("ERR_UNAUTHENTICATED")
    return role


def acting_user_id():
    return flask.request.headers.get("X-User-ID")


def require_role(*roles):
    """The acting role must appear in the operation's grant set."""
    role = acting_role()
    if role not in roles:
        fail("ERR_UNAUTHORIZED")
    return role


def require_advisor_owner(role, resource_advisor_code):
    """AdvisorOps is entity-backed: X-User-ID is the acting Advisor's id.

    Ownership is a foreign-key comparison, so it only bites when the header
    actually names a persisted Advisor: an opaque operator identifier used with
    the AdvisorOps role is recorded but compared to nothing (PRD 2.1).
    """
    if role == "AdvisorOps":
        if acting_user_id() is None:
            fail("ERR_UNAUTHORIZED")
        if resource_advisor_code is None:
            return
        from services import advisors as advisor_service
        actor = advisor_service.find_by_id(acting_user_id())
        if actor is None:
            return
        if actor.get("advisor_code") != resource_advisor_code:
            fail("ERR_UNAUTHORIZED")