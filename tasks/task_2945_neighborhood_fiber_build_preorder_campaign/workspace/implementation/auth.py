"""Identity headers and role authorization (PRD 2.1, ladder steps 1-2)."""

from flask import request

from errors import ApiError

ROLES = (
    "ProgramManager",
    "PermitOffice",
    "UtilityOperator",
    "InstallCoordinator",
    "ClaimsAssessor",
    "ClaimsApprover",
    "Subscriber",
    "MduOwner",
)

ALL_ROLES = ROLES


def identify():
    """Ladder step 1: both headers present, non-empty, role known."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None:
        raise ApiError("ERR_UNAUTHENTICATED", "identity headers are required")
    if user_id.strip() == "" or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED", "identity headers must not be empty")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "unknown role")
    return user_id, role


def gate(allowed):
    """Ladder steps 1 then 2. Returns (user_id, role)."""
    user_id, role = identify()
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN_ROLE", "role %s may not call this endpoint" % role)
    return user_id, role


def own(user_id, role, owner_id, roles=("Subscriber",)):
    """Ladder step 5: account-backed roles may only act on their own rows."""
    if role in roles and user_id != owner_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "acting principal does not own this resource")
