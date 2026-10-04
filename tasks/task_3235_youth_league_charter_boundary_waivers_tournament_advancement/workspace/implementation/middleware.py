"""Auth middleware: X-User-ID + X-User-Role validation and role gating."""
from functools import wraps
from flask import request
from errors import err

ROLES = {
    "DistrictAdministrator",
    "LeagueAdministrator",
    "TournamentDirector",
    "OfficialScorer",
}


def require_auth(allowed_roles):
    """Decorator enforcing validation ladder steps 1 (auth context) and 2 (RBAC).
    allowed_roles: iterable of concrete role names permitted for this operation."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if not user_id or not role or role not in ROLES:
                raise err(
                    "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER",
                    "X-User-ID and X-User-Role headers must be present and valid",
                )
            if role not in allowed_roles:
                raise err(
                    "ERR_INSUFFICIENT_PERMISSIONS",
                    "Role not permitted for this operation",
                )
            return fn(*args, **kwargs)

        return wrapper

    return deco


ANY = ("DistrictAdministrator", "LeagueAdministrator", "TournamentDirector", "OfficialScorer")
