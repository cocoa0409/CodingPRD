"""Auth middleware: X-User-ID + X-User-Role validation and role authorization."""
from functools import wraps
from flask import request

from errors import err

ROLES = {
    "PlatformOps", "Reviewer", "BusinessOwner", "Advertiser",
    "ContentModerator", "TrustInvestigator", "SupportAdmin", "LegalOps",
    "Reporter",
}


def current_actor():
    """Validate headers; return (user_id, role). Raises 401 on missing/unknown."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        raise err("ERR_UNAUTHENTICATED", "missing or unknown X-User-Role header")
    uid = request.headers.get("X-User-ID")
    if uid is None or uid == "":
        raise err("ERR_UNAUTHENTICATED", "missing X-User-ID header")
    return uid, role


def require_roles(*allowed):
    """Decorator: enforce header auth (401) then role authorization (403)."""
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = current_actor()
            if role not in allowed:
                raise err("ERR_FORBIDDEN",
                          f"role {role} not permitted for this endpoint")
            return fn(*args, _actor_id=uid, _actor_role=role, **kwargs)
        return wrapper
    return deco
