"""Auth header extraction and role checking (PRD §2.1)."""
from functools import wraps

from flask import request

from errors import ApiError

ROLES = {"Member", "PartnerAdmin", "Reviewer", "PlatformAdmin"}
ANY_ROLE = None  # accepted for every authenticated role


def actor():
    """Return (role, user_id); raise ERR_UNAUTHENTICATED when malformed."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return role, user_id


def check_role(role, allowed):
    if allowed is ANY_ROLE:
        return
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN")


def require(*allowed):
    """Decorator: authenticate, then enforce the operation's role competence."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            role, user_id = actor()
            check_role(role, allowed if allowed else ANY_ROLE)
            request.actor_role = role
            request.actor_id = user_id
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def acting_role():
    return getattr(request, "actor_role", None)


def acting_id():
    return getattr(request, "actor_id", None)