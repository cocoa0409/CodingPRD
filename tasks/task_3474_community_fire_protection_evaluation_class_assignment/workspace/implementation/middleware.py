"""Auth, role authorization, and entity-backed ownership (PRD §2.1)."""
from flask import request

from errors import fail

ROLES = {
    "EvaluationCoordinator",
    "FieldAnalyst",
    "ClassRegistrar",
    "FireChief",
    "WaterUtilityManager",
    "CommsSupervisor",
    "CommunityOfficial",
    "Insurer",
}


def auth():
    """Priority 1: X-User-ID and X-User-Role present and role known."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "missing or unknown X-User-ID / X-User-Role headers")
    return uid, role


def require_role(role, *allowed):
    """Priority 2: role listed for the endpoint (or owning the target_state)."""
    if role not in allowed:
        fail("ERR_FORBIDDEN", "role %s is not permitted for this endpoint" % role)


def require_owner(cond):
    """Priority 3: entity-backed ownership."""
    if not cond:
        fail("ERR_NOT_OWNER", "caller does not own the target resource")
