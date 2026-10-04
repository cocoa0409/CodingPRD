"""Authentication / authorization middleware (validation cascade priorities 1-2).

Also drives lazy OVERDUE materialization (PRD 2.4) before every API request:
the sweep only mutates ISSUED invoices whose due_at has passed plus the owning
subscriptions, so running it ahead of any request is observationally identical
to running it only before invoice/subscription-touching requests.
"""

import functools

from flask import g, request

from constants import ROLES
from errors import raise_err
from services.billing import materialize_overdue


def authenticate_request():
    """before_request hook: lazy overdue sweep, then header authentication."""
    if not request.path.startswith("/legal-research"):
        return None
    materialize_overdue()
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        user_id is None
        or role is None
        or not user_id.strip()
        or not role.strip()
        or role not in ROLES
    ):
        raise_err("ERR_UNAUTHENTICATED", "X-User-ID and X-User-Role headers must be present, non-blank, and declare a valid role")
    g.user_id = user_id
    g.user_role = role
    return None


def require_roles(*roles):
    """Endpoint role gate: role not on the list -> ERR_FORBIDDEN (403)."""
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            if g.user_role not in roles:
                raise_err("ERR_FORBIDDEN", "role %s is not permitted on this endpoint" % g.user_role)
            return fn(*args, **kwargs)
        return wrapper
    return decorator
