"""Authentication and role-based access control (PRD section 2.1)."""

import functools

from flask import g, request

from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

ROLES = (
    "PlantAdmin",
    "PlantOperator",
    "QualityInspector",
    "ComplianceEngineer",
    "CertificationApprover",
    "SupplierQualityManager",
    "WarrantyAnalyst",
    "SupplierRep",
)

# The seven opaque-identity roles; SupplierRep is the sole entity-backed role.
OPAQUE_ROLES = tuple(r for r in ROLES if r != "SupplierRep")


def endpoint(roles):
    """Wrap a view with ladder positions 1 (authentication) and 2 (authorisation)."""
    allowed = tuple(roles)

    def decorator(view):
        @functools.wraps(view)
        def wrapped(*args, **kwargs):
            user_id = request.headers.get(USER_ID_HEADER)
            role = request.headers.get(USER_ROLE_HEADER)
            if not (user_id or "").strip() or not (role or "").strip():
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in ROLES:
                raise ApiError("ERR_UNAUTHENTICATED")
            if role not in allowed:
                raise ApiError("ERR_FORBIDDEN_ROLE")
            g.user_id = user_id
            g.role = role
            return view(*args, **kwargs)

        return wrapped

    return decorator


def actor_id():
    return getattr(g, "user_id", None)


def actor_role():
    return getattr(g, "role", None)


def is_supplier_rep():
    return actor_role() == "SupplierRep"
