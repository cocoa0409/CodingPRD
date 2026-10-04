"""Auth header extraction and role checking."""
from flask import request
import errors


ROLES = {
    "OpsAdmin",
    "PayerAdmin",
    "PayerRep",
    "ProviderRep",
    "NetworkAdmin",
    "FeedOperator",
    "IdrEntity",
}


def get_auth():
    """Return (user_id, role). Raise ERR_UNAUTHENTICATED if headers invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise errors.unauthenticated()
    return user_id, role


def require_roles(*allowed):
    """Authenticate then check role membership. Returns (user_id, role)."""
    user_id, role = get_auth()
    if role not in allowed:
        raise errors.forbidden()
    return user_id, role
