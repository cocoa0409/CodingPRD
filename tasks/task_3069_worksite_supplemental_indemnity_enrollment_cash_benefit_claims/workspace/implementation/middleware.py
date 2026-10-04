"""Auth middleware: X-User-Role / X-User-ID header extraction and role checks."""
from flask import request

import errors as E

ROLES = {"CarrierAdmin", "GroupAdmin", "BenefitCounselor", "ClaimsAdjuster", "PolicyholderServices"}

# Path prefix of the only endpoint exempt from the auth-header requirement.
_AUTH_EXEMPT = "/_clock/set_current_utc"


def authenticate():
    """Validate auth headers. Returns (user_id, role) or raises ApiError.

    Applied to all endpoints except POST /_clock/set_current_utc.
    """
    if request.path.rstrip("/") == _AUTH_EXEMPT:
        return None, None
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in ROLES or not user_id:
        raise E.err(E.ERR_UNAUTHENTICATED, "Missing or invalid X-User-Role / X-User-ID headers")
    return user_id, role


def require_role(role, allowed):
    if role not in allowed:
        raise E.err(E.ERR_UNAUTHORIZED, "Role not permitted for this endpoint")
