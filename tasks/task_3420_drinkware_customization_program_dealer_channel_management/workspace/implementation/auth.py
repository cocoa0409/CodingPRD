"""Auth context: X-User-ID / X-User-Role headers and role authorization.

Validation priority 1: both headers present and the role names one of the
nine declared roles, else ERR_MISSING_OR_INVALID_CONTEXT_HEADER (400).
Priority 2: role listed on the endpoint plus ownership, else
ERR_FORBIDDEN_FOR_ROLE (403).
"""
from flask import request

from constants import ROLES
from errors import fail


def context():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        fail("ERR_MISSING_OR_INVALID_CONTEXT_HEADER",
             "X-User-ID and X-User-Role headers are required and the role must be declared")
    return uid, role


def require_roles(role, allowed):
    if role not in allowed:
        fail("ERR_FORBIDDEN_FOR_ROLE",
             "role %s is not authorized for this operation" % role)


def forbidden(message="ownership check failed for this resource"):
    fail("ERR_FORBIDDEN_FOR_ROLE", message)
