"""Identity headers and role authorization (PRD 2.1, 2.5 checks 1-2)."""

from flask import request

import db
from errors import ERR_UNAUTHORIZED, ApiError

ROLES = ("Anonymous", "ProgramStaff", "Partner", "Student")

ENTITY_BACKED = {"Partner": "partners", "Student": "students"}


def _unauthorized(message):
    raise ApiError(ERR_UNAUTHORIZED, message, 401)


def authenticate(allow_anonymous=False):
    """Resolve the acting user from X-User-Role / X-User-ID.

    Anonymous registration is the one operation that needs no credentials.
    """
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")

    if role is None or role.strip() == "":
        if allow_anonymous:
            return {"role": "Anonymous", "user_id": user_id}
        _unauthorized("X-User-Role header is required")

    role = role.strip()
    if role not in ROLES:
        _unauthorized("X-User-Role '%s' is not a declared role" % role)

    if role == "Anonymous":
        return {"role": role, "user_id": user_id}

    if user_id is None or user_id.strip() == "":
        _unauthorized("X-User-ID header is required for role %s" % role)
    user_id = user_id.strip()

    table = ENTITY_BACKED.get(role)
    if table is not None and db.get(table, user_id) is None:
        _unauthorized("X-User-ID does not resolve to a %s" % role)

    return {"role": role, "user_id": user_id}


def authorize(actor, allowed):
    """Role matrix check; a valid role outside the endpoint's list is 401."""
    if actor["role"] not in allowed:
        _unauthorized(
            "role %s is not authorized for this operation" % actor["role"]
        )
    return actor


def require(allowed, allow_anonymous=False):
    actor = authenticate(allow_anonymous=allow_anonymous)
    authorize(actor, allowed)
    return actor
