"""Authentication and role authorization (ladder tiers 1-2, PRD §2.1).

Every request must carry X-User-ID and X-User-Role; the role must name one of
the four declared roles. Each endpoint then admits a fixed role list.
"""

from functools import wraps

from flask import request

from errors import (ApiError, ERR_FORBIDDEN_FOR_ROLE,
                    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)

ROLE_BREWER_ADMIN = "BrewerAdmin"
ROLE_BREWER_COMPLIANCE = "BrewerCompliance"
ROLE_WHOLESALER_PRINCIPAL = "WholesalerPrincipal"
ROLE_DRAFT_AUDITOR = "DraftAuditor"

DECLARED_ROLES = frozenset({
    ROLE_BREWER_ADMIN,
    ROLE_BREWER_COMPLIANCE,
    ROLE_WHOLESALER_PRINCIPAL,
    ROLE_DRAFT_AUDITOR,
})

ALL_ROLES = (ROLE_BREWER_ADMIN, ROLE_BREWER_COMPLIANCE,
             ROLE_WHOLESALER_PRINCIPAL, ROLE_DRAFT_AUDITOR)


def user_context():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in DECLARED_ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role headers must both be present and "
            "non-empty, and X-User-Role must name a declared role",
            400,
        )
    return user_id, role


def require_roles(*roles):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = user_context()
            if role not in roles:
                raise ApiError(
                    ERR_FORBIDDEN_FOR_ROLE,
                    "Role %s is not authorized for this endpoint" % role,
                    403,
                )
            kwargs["user_id"] = user_id
            kwargs["caller_role"] = role
            return fn(*args, **kwargs)
        return wrapper
    return decorator
