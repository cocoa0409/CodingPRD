"""Authentication, role authorisation and request-body plumbing."""
from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = ("TerminalAdmin", "SalesAssociate", "StockController", "CustomsAuditor", "Passenger")


def _authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role


def endpoint(*roles):
    """Tier 1 (authentication) then tier 2 (role authorisation) of PRD section 2.8."""
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            _authenticate()
            if g.role not in roles:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            payload = request.get_json(silent=True)
            g.body = payload if isinstance(payload, dict) else {}
            g.bumped_items = set()
            return view(*args, **kwargs)
        return wrapper
    return decorator


def body():
    return getattr(g, "body", {}) or {}


def actor():
    return g.user_id


def role():
    return g.role


def is_passenger():
    return g.role == "Passenger"
