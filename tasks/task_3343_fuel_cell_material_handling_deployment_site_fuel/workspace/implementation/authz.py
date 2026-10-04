"""Authentication and role-based authorization (PRD section 2.1).

Every request must carry X-User-ID and X-User-Role. A missing or unrecognized
role (or a missing user id) is ERR_UNAUTHENTICATED (401); a recognized role
that is not permitted on the endpoint is ERR_FORBIDDEN (403).
"""

import functools

from flask import request, g

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ROLES = {
    "PlatformAdmin",
    "SiteManager",
    "SafetyOfficer",
    "ComplianceOfficer",
    "ConversionTechnician",
    "BillingOperator",
}


def require_roles(*allowed):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            role = request.headers.get("X-User-Role")
            uid = request.headers.get("X-User-ID")
            if not role or role not in ROLES or not uid:
                raise ApiError(
                    ERR_UNAUTHENTICATED, 401,
                    "X-User-ID and a recognized X-User-Role header are required",
                )
            if role not in allowed:
                raise ApiError(
                    ERR_FORBIDDEN, 403,
                    "role %s is not permitted for this endpoint" % role,
                )
            g.user_role = role
            g.user_id = uid
            return fn(*args, **kwargs)
        return wrapper
    return decorator
