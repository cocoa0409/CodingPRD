"""Authentication (priority 10), role permission (priority 20) and
resource ownership (priority 60)."""

from flask import request

from errors import fail

ROLES = (
    "ProjectAdmin",
    "WellfieldTechnician",
    "PlantOperator",
    "CommercialScheduler",
    "ComplianceOfficer",
    "HostRepresentative",
    "Offtaker",
)


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def authenticate():
    """Priority 10: both headers present and the role recognised."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id == "" or role == "":
        fail("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers are required.")
    if role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "X-User-Role is not a recognised role.")
    return Caller(user_id, role)


def require_role(caller, allowed):
    """Priority 20: the acting role appears in the endpoint's permitted list."""
    if caller.role not in allowed:
        fail("ERR_ROLE_NOT_PERMITTED", "Role %s may not call this endpoint." % caller.role)


def deny_role(message="Role is not permitted for this operation."):
    fail("ERR_ROLE_NOT_PERMITTED", message)


def require_owner(caller, owner_id):
    """Priority 60: an entity-backed role acting on a resource it owns."""
    if caller.user_id != owner_id:
        fail("ERR_NOT_RESOURCE_OWNER", "The acting identity does not own this resource.")
