"""Authentication, role authorization, and ownership (pipeline priorities 1-3).

P1: X-User-ID and X-User-Role present, role names one of the six declared
roles — else ERR_UNAUTHENTICATED (401).
P2: role listed for the endpoint (including the action-level split on the
report verification endpoint) — else ERR_FORBIDDEN (403).
P3: ownership — Specifier operations compare X-User-ID against the resource's
created_by; Installer operations compare it against the site's contractor_name
— else ERR_FORBIDDEN (403). Ownership can only be evaluated once the anchor
resource exists; a missing anchor falls through to the P4 existence error.
"""
from flask import request

from constants import ALL_ROLES
from errors import ApiError


def authenticate():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ALL_ROLES:
        raise ApiError(
            "ERR_UNAUTHENTICATED",
            401,
            "X-User-ID and X-User-Role headers are required and the role must be declared",
        )
    return uid, role


def authorize(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_FORBIDDEN", 403, "Role %s is not permitted on this endpoint" % role)


def forbid(message):
    raise ApiError("ERR_FORBIDDEN", 403, message)
