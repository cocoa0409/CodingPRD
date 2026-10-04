"""Authentication (priority 2) and endpoint role membership (priority 3).
X-User-ID + X-User-Role are mandatory on every request. An unknown role value
is malformed -> 401. Role not listed for the endpoint -> 403.
"""
from flask import request
import errors
from constants import ROLES


def actor():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or uid.strip() == "":
        errors.unauthenticated("X-User-ID header missing or malformed")
    if role is None or role.strip() == "":
        errors.unauthenticated("X-User-Role header missing or malformed")
    if role not in ROLES:
        errors.unauthenticated("X-User-Role header missing or malformed")
    return uid, role


def require_roles(*roles):
    uid, role = actor()
    if role not in roles:
        errors.unauthorized("role %s is not permitted on this endpoint" % role)
    return uid, role
