"""Authentication, authorization and the per-request mutation bookkeeping.

PRD 2.1: every request carries X-User-ID and X-User-Role. Authentication is
checked before authorization, and both before anything else about the request.
"""

from functools import wraps

from flask import g, request

import clock
import errors

ROLE_PROGRAM_DESIGNER = "ProgramDesigner"
ROLE_INCENTIVE_CONTROLLER = "IncentiveController"
ROLE_FIELD_SALES_MANAGER = "FieldSalesManager"
ROLE_CLAIMS_AUDITOR = "ClaimsAuditor"
ROLE_DEALER = "Dealer"

ALL_ROLES = (
    ROLE_PROGRAM_DESIGNER,
    ROLE_INCENTIVE_CONTROLLER,
    ROLE_FIELD_SALES_MANAGER,
    ROLE_CLAIMS_AUDITOR,
    ROLE_DEALER,
)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ALL_ROLES:
        raise errors.ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.user_role = role
    return user_id, role


def require_roles(*allowed):
    """Decorator running rung 1 (authentication) then rung 2 (authorization)."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            _, role = authenticate()
            if role not in allowed:
                raise errors.ApiError("ERR_UNAUTHORIZED")
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def caller_id():
    return getattr(g, "user_id", None)


def caller_role():
    return getattr(g, "user_role", None)


def touch(entity):
    """Mark an entity as mutated by this request.

    PRD 2.9: every affected entity's version has incremented by 1 and its
    updated_at has been refreshed by the time the response is returned. The
    increment is exactly 1 per entity per request, however many cascade links
    touched it.
    """
    if entity is None or "version" not in entity:
        return entity
    touched = getattr(g, "_touched", None)
    if touched is None:
        touched = set()
        g._touched = touched
    key = (entity.get("_kind"), entity.get("id"))
    entity["updated_at"] = clock.now()
    if key not in touched:
        touched.add(key)
        entity["version"] = entity["version"] + 1
    return entity
