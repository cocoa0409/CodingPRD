"""Authorisation: header validity, endpoint permission and action scoping.

Every request carries X-User-ID and X-User-Role (PRD 2.1).  Authorisation is
checked before anything else about the request is examined.
"""
from functools import wraps

from flask import request

from errors import fail

ROLES = (
    "RegistryAdmin",
    "ComplianceAnalyst",
    "ToxicologyReviewer",
    "LabelingSpecialist",
    "RegulatoryCounsel",
    "SupplierPortalUser",
)

READ_ALL_BUT_SUPPLIER = (
    "RegistryAdmin", "ComplianceAnalyst", "ToxicologyReviewer",
    "LabelingSpecialist", "RegulatoryCounsel",
)


class Caller(object):
    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role


def caller(allowed_roles):
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        fail("ERR_UNAUTHORIZED", "X-User-Role is absent or not a declared role")
    if role not in allowed_roles:
        fail("ERR_UNAUTHORIZED", "role %s is not authorised for this endpoint" % role)
    return Caller(request.headers.get("X-User-ID"), role)


def guard(*allowed_roles):
    """Bind endpoint authorisation to a view; the view receives the caller."""
    def decorator(view):
        @wraps(view)
        def wrapper(**kwargs):
            who = caller(allowed_roles)
            return view(who, **kwargs)
        return wrapper
    return decorator


def action_role(action, mapping, role):
    """Action scoping on shared transition surfaces: wrong role -> 403."""
    permitted = mapping.get(action)
    if permitted is not None and role not in permitted:
        fail("ERR_UNAUTHORIZED",
             "role %s may not perform %s on this surface" % (role, action))
