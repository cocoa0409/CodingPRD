"""Auth middleware per PRD §2.1.

Every request must carry X-User-ID and X-User-Role. X-User-Role must be one of
the five roles and must be authorized for the target endpoint. Role-specific
identity semantics: Driver identity is the Driver entity id; all other roles
use opaque identifiers.
"""
from functools import wraps

from flask import request

from errors import err_unauthorized

ROLES = ("PlatformAdmin", "IncentiveOps", "PaymentsOfficer", "FraudAnalyst", "Driver")


def current_user():
    """Return (user_id, role) after validating headers, or raise."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise err_unauthorized()
    if role not in ROLES:
        raise err_unauthorized()
    return user_id, role


def require_roles(*allowed):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = current_user()
            if role not in allowed:
                raise err_unauthorized()
            return fn(*args, _user_id=user_id, _role=role, **kwargs)

        return wrapper

    return deco
