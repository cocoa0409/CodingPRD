"""Request middleware: identity headers, the RBAC gate and OCC helpers.

PRD §2.1 pins the header names (``X-User-ID`` / ``X-User-Role``) and the eight
recognised role spellings. Authentication is checked before anything else, and a
role that is not permitted for the operation -- including one the platform does
not recognise -- is an authorisation failure, not an authentication failure.
"""

import uuid
from functools import wraps

from flask import request

from db import now
from errors import (ApiError, ERR_STALE_VERSION, ERR_UNAUTHENTICATED,
                    ERR_UNAUTHORIZED)

ROLES = (
    "PlatformAdmin",
    "SafetyInvestigator",
    "SafetyAppealReviewer",
    "SafetyOperationsLead",
    "RegulatorLiaison",
    "BackgroundReviewer",
    "Rider",
    "Driver",
)

ENTITY_BACKED_ROLES = ("Rider", "Driver")


class Identity:
    """The acting operator extracted from the mandatory headers."""

    def __init__(self, user_id, role):
        self.user_id = user_id
        self.role = role

    def is_entity_backed(self):
        return self.role in ENTITY_BACKED_ROLES


def _identity():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role:
        raise ApiError(*ERR_UNAUTHENTICATED,
                       message="X-User-ID and X-User-Role are required.")
    return Identity(user_id, role)


def route(*allowed_roles):
    """Declare the exhaustive authorised-role list for an operation."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            ident = _identity()
            if ident.role not in ROLES:
                raise ApiError(*ERR_UNAUTHORIZED,
                               message="Unknown role %r." % ident.role)
            if allowed_roles and ident.role not in allowed_roles:
                raise ApiError(
                    *ERR_UNAUTHORIZED,
                    message="Role %s is not permitted for this operation."
                            % ident.role)
            return fn(ident, *args, **kwargs)

        return wrapper

    return decorator


def new_id():
    """A server-minted identifier formatted as a bare UUID."""
    return str(uuid.uuid4())


def stamp(resource):
    """Initialise the system-managed skeleton of a freshly created resource."""
    instant = now()
    resource["id"] = resource.get("id") or new_id()
    resource["created_at"] = instant
    resource["updated_at"] = instant
    resource["version"] = resource.get("version", 1)
    return resource


def touch(resource):
    """Refresh updated_at and bump version after a mutation."""
    resource["updated_at"] = now()
    resource["version"] = int(resource.get("version", 1)) + 1
    return resource


def require_version(payload, field, label=None):
    """The six protected writes require their expectation field: it is never optional."""
    if not isinstance(payload, dict) or field not in payload or payload.get(field) is None:
        raise ApiError(*ERR_STALE_VERSION,
                       message="%s is required." % (label or field))
    return payload.get(field)


def assert_version_matches(payload, field, resource, label=None):
    """Compare the client's observed version against the stored one."""
    try:
        expected = int(payload.get(field))
    except (TypeError, ValueError):
        raise ApiError(*ERR_STALE_VERSION,
                       message="%s must be an integer." % (label or field))
    if expected != int(resource.get("version", 1)):
        raise ApiError(*ERR_STALE_VERSION,
                       message="The observed version of %s is stale." % (label or field))


def body():
    return request.get_json(silent=True) or {}


def require(body_dict, field):
    value = body_dict.get(field)
    if value is None:
        raise ApiError(*ERR_UNAUTHORIZED,
                       message="%s is required." % field)
    return value