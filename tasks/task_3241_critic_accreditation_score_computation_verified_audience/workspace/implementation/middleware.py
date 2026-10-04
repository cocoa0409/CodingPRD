"""Auth middleware (PRD 2.1): header extraction and role checking."""
from flask import request
from errors import err

VALID_ROLES = {"PlatformAdmin", "AccreditationBoard", "Critic", "StudioRep", "AudienceMember"}

OPAQUE_ROLES = {"PlatformAdmin", "AccreditationBoard", "StudioRep"}
ENTITY_ROLES = {"Critic": "critic", "AudienceMember": "audience_member"}


def get_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in VALID_ROLES:
        raise err("ERR_UNAUTHENTICATED", "Missing or invalid X-User-ID / X-User-Role headers")
    return user_id, role


def require_roles(*roles):
    """Authenticate, then authorize against the allowed role set."""
    user_id, role = get_auth()
    if role not in roles:
        raise err("ERR_UNAUTHORIZED", "Role %s is not permitted for this endpoint" % role)
    return user_id, role
