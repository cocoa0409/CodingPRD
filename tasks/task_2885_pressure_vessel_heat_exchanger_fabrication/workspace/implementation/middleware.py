"""Authentication, identity resolution and role permission.

Ladder steps 1 to 3 of PRD section 2.8.
"""

from functools import wraps

import db
from errors import fail

ROLES = ("ShopAdmin", "DesignEngineer", "WeldingEngineer", "QCInspector",
         "AuthorizedInspector")

# The four person-backed roles and the Personnel.role_code each resolves to.
ROLE_CODE_FOR_ROLE = {
    "DesignEngineer": "DESIGN_ENGINEER",
    "WeldingEngineer": "WELDING_ENGINEER",
    "QCInspector": "QC_INSPECTOR",
    "AuthorizedInspector": "AUTHORIZED_INSPECTOR",
}


class Ctx(object):
    __slots__ = ("role", "user_id", "person")

    def __init__(self, role, user_id, person):
        self.role = role
        self.user_id = user_id
        self.person = person


def _authenticate(resolve_identity):
    from flask import request

    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    if role is None or role not in ROLES:
        fail("ERR_UNAUTHENTICATED", "Header 'X-User-Role' is absent or undeclared.")

    person_backed = role in ROLE_CODE_FOR_ROLE
    if person_backed and (user_id is None or user_id.strip() == ""):
        fail("ERR_UNAUTHENTICATED", "Header 'X-User-ID' is required for a person-backed role.")

    person = None
    if person_backed and resolve_identity:
        person = db.get("personnel", user_id)
        if person is None or person.get("role_code") != ROLE_CODE_FOR_ROLE[role]:
            fail("ERR_IDENTITY_ROLE_MISMATCH",
                 "Header 'X-User-ID' does not resolve to a %s person record." % role)

    return Ctx(role, user_id, person)


def guard(roles, resolve_identity=True):
    """Wrap a handler with ladder steps 1 to 3, in that order."""

    def decorator(handler):
        @wraps(handler)
        def wrapper(**path_params):
            ctx = _authenticate(resolve_identity)
            if ctx.role not in roles:
                fail("ERR_ROLE_NOT_PERMITTED",
                     "Role '%s' is not permitted on this endpoint." % ctx.role)
            return handler(ctx, **path_params)

        return wrapper

    return decorator


ALL_ROLES = ROLES
