"""Authentication and role authorisation (PRD §2.1, ladder rungs 1 and 2)."""

import functools

from flask import g, request

from errors import ApiError

ROLES = (
    "VenueOpsManager",
    "LicensingManager",
    "LicensorRep",
    "ExperienceProducer",
    "SafetyOfficer",
    "GuestServicesAgent",
    "Guest",
)

# convenience aliases used by the route modules
VOM = "VenueOpsManager"
LM = "LicensingManager"
LR = "LicensorRep"
EP = "ExperienceProducer"
SO = "SafetyOfficer"
GSA = "GuestServicesAgent"
GUEST = "Guest"

CLOCK_ROLES = (VOM, LM, LR, EP, SO, GSA)


def authenticate():
    """Rung 1 — both identity headers must be present, non-blank and known."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role is None or role.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    g.user_id = user_id
    g.role = role
    return user_id, role


def roles(*allowed):
    """Decorator applying rung 1 then rung 2 before the handler body runs."""

    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            _, role = authenticate()
            if role not in allowed:
                raise ApiError("ERR_UNAUTHORIZED")
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def caller_id():
    return g.user_id


def caller_role():
    return g.role
