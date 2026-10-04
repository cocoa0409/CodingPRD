"""Authentication and RBAC (PRD 2.1, scaffold validations priorities 1-4).

Headers: X-User-ID and X-User-Role.  Fourteen case-sensitive role names.
Eleven roles are opaque operators; three are entity-backed:
  CorpsOfficer     -> Unit        (X-User-ID is a Unit id)
  BellRinger       -> BellRinger  (X-User-ID is a BellRinger id)
  HostSiteManager  -> HostSite    (X-User-ID is a HostSite id)
"""
from flask import request

from . import store
from .errors import ApiError

ROLE_NAMES = (
    "PlatformAdmin",
    "TerritorialCommander",
    "DivisionalOfficer",
    "CorpsOfficer",
    "KettleCoordinator",
    "VolunteerCoordinator",
    "BellRinger",
    "CountingRoomTeller",
    "FinanceOfficer",
    "AssistanceCaseworker",
    "ProgramDirector",
    "DisasterServicesCoordinator",
    "DigitalGivingProcessor",
    "HostSiteManager",
)

OPAQUE_ROLES = (
    "PlatformAdmin",
    "TerritorialCommander",
    "DivisionalOfficer",
    "KettleCoordinator",
    "VolunteerCoordinator",
    "CountingRoomTeller",
    "FinanceOfficer",
    "AssistanceCaseworker",
    "ProgramDirector",
    "DisasterServicesCoordinator",
    "DigitalGivingProcessor",
)

# role -> (table, attribute holding the owning foreign key on a scoped resource)
ENTITY_BACKED = {
    "CorpsOfficer": ("units", "corps_id"),
    "BellRinger": ("bell_ringers", "bell_ringer_id"),
    "HostSiteManager": ("host_sites", "host_site_id"),
}


def _headers():
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    return role, user_id


def require_role(allowed):
    """Ladder steps 1-3.  Returns (role, user_id)."""
    role, user_id = _headers()
    if not role or not str(role).strip() or not user_id or not str(user_id).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    role = str(role).strip()
    user_id = str(user_id).strip()
    if role not in ROLE_NAMES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN")
    return role, user_id


def is_entity_backed(role):
    return role in ENTITY_BACKED


def owner_guard(role, user_id, owner_id):
    """Ladder step 4 for an owner-scoped operation.

    Only entity-backed roles are compared.  `owner_id` is the addressed
    resource's owning foreign key (or its own id for a self-owned resource).
    """
    if role not in ENTITY_BACKED:
        return
    table, _attr = ENTITY_BACKED[role]
    if store.find(table, user_id) is None:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
    if owner_id is not None and str(owner_id) != str(user_id):
        raise ApiError("ERR_NOT_RESOURCE_OWNER")


def backing_entity_guard(role, user_id):
    """Ladder step 4 for an entity-backed role acting on a resource that does
    not expose a comparable owning foreign key."""
    if role not in ENTITY_BACKED:
        return
    table, _attr = ENTITY_BACKED[role]
    if store.find(table, user_id) is None:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")
