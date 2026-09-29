"""Authentication, role authorization and participant ownership (PRD 2.1, 2.8)."""

from flask import request

from errors import fail
from store import db

ROLES = (
    "ProgramDirector",
    "SourcingManager",
    "ContractApprover",
    "SalesOpsAnalyst",
    "TravelDesk",
    "TaxComplianceOfficer",
    "Participant",
)

ALL_ROLES = list(ROLES)
OPERATOR_ROLES = [r for r in ROLES if r != "Participant"]


class Actor(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_participant(self):
        return self.role == "Participant"


def authorize(*allowed_roles):
    """Priorities 1, 2 and 3 of the validation ladder, in that order."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")

    if user_id is None or not user_id.strip() or role is None or not role.strip():
        fail("ERR_MISSING_AUTH_HEADERS")
    if role not in ROLES:
        fail("ERR_INVALID_ROLE")
    if role not in allowed_roles:
        fail("ERR_ROLE_NOT_PERMITTED")
    return Actor(user_id, role)


# -------------------------------------------------------------- ownership (6)
def own_qualifier(actor, qualifier_id):
    """Participant may only touch rows owned by the qualifier they are."""
    if actor.is_participant and actor.user_id != qualifier_id:
        fail("ERR_NOT_RESOURCE_OWNER")


def own_registration(actor, registration):
    own_qualifier(actor, registration["qualifier_id"])


def own_signup(actor, signup):
    if not actor.is_participant:
        return
    registration = db.registrations.get(signup["registration_id"])
    owner = registration["qualifier_id"] if registration else None
    if actor.user_id != owner:
        fail("ERR_NOT_RESOURCE_OWNER")
