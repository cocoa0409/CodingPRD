"""Header extraction, role validation and the RBAC matrix.

Order is normative (PRD 2.12): the two auth checks run before anything else,
so priority 1 (header shape) always beats priority 2 (role permitted).
"""

from functools import wraps

from flask import request

import constants as K
from error import (
    CatalogError,
    ERR_FORBIDDEN_FOR_ROLE,
    ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
)

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

# Roles permitted for an endpoint that declares "any authenticated caller".
ANY = object()


class Caller(object):
    __slots__ = ("user_id", "role")

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    @property
    def is_partner_ops(self):
        return self.role == "PartnerOps"


def caller_from_headers():
    """Priority 1: both headers present and the role declared."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if user_id is None or user_id == "" or role is None or role == "":
        raise CatalogError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-ID and X-User-Role are both required.",
        )
    if role not in K.ROLES:
        raise CatalogError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            "X-User-Role '%s' is not a declared role." % role,
        )
    return Caller(user_id, role)


def require_role(caller, allowed):
    """Priority 2: the declared role must appear in the endpoint's list."""
    if allowed is ANY:
        return caller
    if caller.role not in allowed:
        raise CatalogError(
            ERR_FORBIDDEN_FOR_ROLE,
            "Role '%s' is not permitted for this operation." % caller.role,
        )
    return caller


def roles(*allowed):
    """Decorator: validate the headers, then the role, then run the handler."""

    def decorator(handler):
        @wraps(handler)
        def wrapper(*args, **kwargs):
            caller = caller_from_headers()
            require_role(caller, set(allowed) if allowed else ANY)
            return handler(caller, *args, **kwargs)

        return wrapper

    return decorator


def require_self(caller, partner_id, field="partner_id"):
    """Ownership check for the entity-backed PartnerOps role.

    Only PartnerOps is entity-backed (PRD 2.1); the operator roles record the
    identifier on the audit trail but are never compared against an entity.
    """
    if not caller.is_partner_ops:
        return
    if partner_id is not None and caller.user_id != partner_id:
        raise CatalogError(
            ERR_FORBIDDEN_FOR_ROLE,
            "PartnerOps caller '%s' may not act for partner '%s'." % (caller.user_id, partner_id),
        )