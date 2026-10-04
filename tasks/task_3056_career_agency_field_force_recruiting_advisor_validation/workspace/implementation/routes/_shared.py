"""Decorators shared by every route module.

The decorators encode PRD §2.10's outermost precedence: the auth context check,
then the RBAC grant, both before any resource lookup.
"""

from functools import wraps

from middleware import actor, require
from services import derived
from db import db


def authed(allowed):
    """Resolve the acting principal, apply the logical-clock sweep, check RBAC."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = actor()
            with db._lock:
                derived.sweep_expiries()
                derived.refresh_all_dimensions()
                require(role, allowed)
                return fn(user_id, role, *args, **kwargs)
        return wrapper
    return decorator