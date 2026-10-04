"""Authentication and role-authorization middleware (PRD section 2.1).

Validation tiers 1 and 2: headers present + recognized role (401), then the
caller's role listed for the operation (403).
"""
from functools import wraps

from flask import request

from errors import ApiError

ALL_ROLES = (
    "PlatformAdmin",
    "FacilityOwner",
    "Importer",
    "EntryReviewer",
    "ComplianceOfficer",
    "FieldInspector",
    "RecallCoordinator",
)


def require_roles(*roles):
    """Gate a view: 401 unless both headers are present and the role is one
    of the seven; 403 unless the role is authorized for this endpoint."""

    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid = request.headers.get("X-User-ID") or ""
            role = request.headers.get("X-User-Role") or ""
            if not uid.strip() or role not in ALL_ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in roles:
                raise ApiError("ERR_FORBIDDEN")
            kwargs["caller_id"] = uid
            kwargs["caller_role"] = role
            return fn(*args, **kwargs)

        return wrapper

    return deco
