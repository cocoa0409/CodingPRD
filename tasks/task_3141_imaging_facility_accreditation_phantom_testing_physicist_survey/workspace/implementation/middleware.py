"""Auth header extraction and role checking (PRD §2.1, §2.12 priorities 1–2)."""

from functools import wraps

import flask

from errors import fail

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

DECLARED_ROLES = {
    "FacilityAdmin",
    "MedicalPhysicist",
    "AccreditationBody",
    "Any",
    "Anonymous",
}

# `Anonymous` exists only for negative scenarios and is never authorized.
NON_ACTING_ROLES = {"Anonymous"}


class Principal:
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    def __repr__(self):
        return f"Principal({self.user_id!r}, {self.role!r})"


def authenticate():
    """Priority 1 — headers present and naming a declared role."""
    user_id = flask.request.headers.get(USER_ID_HEADER)
    role = flask.request.headers.get(USER_ROLE_HEADER)
    if not user_id or not role:
        fail("ERR_UNAUTHENTICATED", "missing X-User-ID or X-User-Role header")
    if role not in DECLARED_ROLES:
        fail("ERR_UNAUTHENTICATED", "undeclared role")
    return Principal(user_id, role)


def authorized(principal, roles):
    """Priority 2 — the acting role is listed on the target endpoint's roles."""
    if principal.role in NON_ACTING_ROLES:
        fail("ERR_UNAUTHORIZED", "the acting role is not permitted to call this endpoint")
    if "Any" in roles:
        return
    if principal.role in roles:
        return
    fail("ERR_UNAUTHORIZED", "the acting role is not permitted to call this endpoint")


def require(roles):
    """Decorator: authenticate, then authorize against the endpoint's roles."""
    def decorator(handler):
        @wraps(handler)
        def wrapper(*args, **kwargs):
            principal = authenticate()
            authorized(principal, roles)
            return handler(principal, *args, **kwargs)
        return wrapper
    return decorator

