"""Auth header extraction, role checking and driver-scoped ownership helpers.

Transcribed from SCAFFOLD.yaml section 1.4 validations priority 1-2 and PRD
section 2.1:
  - headers: X-User-ID and X-User-Role, both mandatory
  - roles: Anonymous, DistrictAdmin, Driver, SupportCenterAgent, PlatformAdmin
  - only the Driver role is entity-backed
"""

import functools

from errors import (
    ERR_FORBIDDEN,
    ERR_UNAUTHENTICATED,
    ApiError,
)
from flask import request

import db

IDENTITY_HEADER = "X-User-ID"
ROLE_HEADER = "X-User-Role"

KNOWN_ROLES = ("Anonymous", "DistrictAdmin", "Driver", "SupportCenterAgent", "PlatformAdmin")

# PlatformAdmin is a superset: it may call every DistrictAdmin and
# SupportCenterAgent operation plus its own (PRD section 2.1).
_SUPERSET_OF = {"DistrictAdmin", "SupportCenterAgent"}


def read_actor():
    """Extract (user_id, role) from the mandatory identity headers."""
    user_id = request.headers.get(IDENTITY_HEADER)
    role = request.headers.get(ROLE_HEADER)
    if not user_id or not role or role not in KNOWN_ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED,
            "X-User-ID and X-User-Role headers are required and X-User-Role must name a known role.",
        )
    return user_id, role


def role_permitted(role, allowed):
    if role in allowed:
        return True
    if role == "PlatformAdmin" and (set(allowed) & _SUPERSET_OF):
        return True
    return False


def check_permitted(user_id, role, allowed):
    """Priority 2: the acting role must be permitted for this operation.

    Driver is entity-backed, so a Driver caller must carry the id of a
    persisted Driver instance.
    """
    if not role_permitted(role, allowed):
        raise ApiError(
            ERR_FORBIDDEN,
            f"Role {role} is not permitted to perform this operation.",
        )
    if role == "Driver" and user_id not in db.STORE.drivers:
        raise ApiError(
            ERR_FORBIDDEN,
            "X-User-ID does not identify a persisted Driver.",
        )


def requires(*allowed_roles):
    """Decorator: authenticate, then authorise against the role list."""

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id, role = read_actor()
            check_permitted(user_id, role, allowed_roles)
            request.actor_id = user_id
            request.actor_role = role
            return view(*args, **kwargs)

        return wrapper

    return decorator


def actor_id():
    return getattr(request, "actor_id", None)


def actor_role():
    return getattr(request, "actor_role", None)


def mask_phone(phone):
    """Keep the final four digits and mask every other character."""
    if phone is None:
        return None
    text = str(phone)
    if len(text) <= 4:
        return "*" * len(text)
    return "*" * (len(text) - 4) + text[-4:]