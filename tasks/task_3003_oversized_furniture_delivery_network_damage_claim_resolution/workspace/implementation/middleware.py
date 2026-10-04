"""Auth header extraction and RBAC.

Validation order (PRD §2.7): auth presence (401) -> role authorization (403) ->
identifier existence (404) -> field validity (400) -> state (409) -> business rules.
"""
import functools

from flask import request

from errors import err_forbidden, err_unauthenticated

ROLES = {
    "NetworkAdmin",
    "Customer",
    "HubOperator",
    "ClaimsAdjuster",
    "SupplierRep",
    "CarrierRep",
}


def require_roles(*roles):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user_id = request.headers.get("X-User-ID")
            role = request.headers.get("X-User-Role")
            if user_id is None or user_id.strip() == "" or role is None or role.strip() == "":
                raise err_unauthenticated()
            if role not in ROLES or role not in roles:
                raise err_forbidden()
            request.user_id = user_id
            request.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator
