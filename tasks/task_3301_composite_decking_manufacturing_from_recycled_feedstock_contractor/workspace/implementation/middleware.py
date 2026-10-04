"""Auth middleware: X-User-ID / X-User-Role extraction and role checking."""
import functools
from flask import request, g

from errors import raise_err, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = {
    "OpsManager", "QualityEngineer", "ProcessEngineer", "ProductManager",
    "ChannelManager", "DealerSalesRep", "Dealer", "ProgramAdmin",
    "Contractor", "ClaimsAdjuster",
}


def authenticate():
    """Priority-1 auth check: headers present and role declared."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not user_id or not role or role not in ROLES:
        raise_err(ERR_UNAUTHENTICATED, "missing or unknown role/user headers")
    g.user_id = user_id
    g.role = role


def require_roles(*roles):
    """Decorator: authenticate, then enforce role membership (priority 2)."""
    def wrapper(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            authenticate()
            if g.role not in roles:
                raise_err(ERR_UNAUTHORIZED, "role not permitted for endpoint")
            return fn(*args, **kwargs)
        return inner
    return wrapper
