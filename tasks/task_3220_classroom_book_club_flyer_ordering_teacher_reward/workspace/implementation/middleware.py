"""Auth middleware: X-User-ID / X-User-Role validation and per-endpoint role checks."""

import functools

from flask import request

from errors import raise_err

ROLES = {"ClubAdmin", "SchoolAdmin", "Teacher", "Parent", "Donor"}


def current_role():
    return request.headers.get("X-User-Role")


def current_user_id():
    return request.headers.get("X-User-ID")


def require_auth():
    """Priority 1: headers present and role declared."""
    role = current_role()
    uid = current_user_id()
    if not role or not uid or role not in ROLES:
        raise_err("ERR_UNAUTHENTICATED", "Missing or invalid X-User-Role / X-User-ID headers")
    return role, uid


def require_roles(*allowed):
    """Decorator: enforce auth (401) then role authorization (403)."""

    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            role, uid = require_auth()
            if role not in allowed:
                raise_err("ERR_UNAUTHORIZED", "Role %s not permitted for this endpoint" % role)
            return fn(*args, **kwargs)

        return wrapper

    return deco
