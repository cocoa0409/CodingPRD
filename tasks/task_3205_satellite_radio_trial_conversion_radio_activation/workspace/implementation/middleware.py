"""Auth: X-User-Role / X-User-ID headers per PRD 2.1."""
from flask import request

import errors

DECLARED_ROLES = {
    "PlatformAdmin", "AutomakerPartner", "DealerPartner",
    "Customer", "RetentionAgent", "SystemOperator", "Anonymous",
}
ENTITY_BACKED = {"AutomakerPartner", "DealerPartner", "Customer"}


def get_auth():
    """Returns (role, user_id). Raises ERR_UNAUTHENTICATED."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in DECLARED_ROLES:
        raise errors.unauthenticated()
    if role in ENTITY_BACKED and not user_id:
        raise errors.unauthenticated()
    return role, user_id


def require_roles(allowed):
    role, user_id = get_auth()
    if role not in allowed:
        raise errors.unauthorized()
    return role, user_id
