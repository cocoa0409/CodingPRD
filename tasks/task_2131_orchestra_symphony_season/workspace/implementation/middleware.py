"""Authentication, authorisation and ownership rungs (PRD 2.1 / 2.6)."""

from functools import wraps

from flask import g, request

from errors import raise_err

ROLES = (
    "ArtisticAdmin",
    "OrchestraManager",
    "BoxOfficeAgent",
    "Patron",
    "Musician",
    "GuestArtist",
    "AdvertisingSales",
)

ENTITY_BACKED = ("Patron", "Musician", "GuestArtist")


def authenticate():
    """Rung 1 — both headers present and the role is one of the seven."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise_err("ERR_UNAUTHENTICATED")
    return user_id, role


def authorize(role, allowed):
    """Rung 2 — the acting role appears in the endpoint's role list."""
    if role not in allowed:
        raise_err("ERR_UNAUTHORIZED")


def endpoint(roles):
    """Decorator applying rungs 1 and 2 before the handler body runs."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            authorize(role, roles)
            g.user_id = user_id
            g.user_role = role
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def own(expected_id, role_name):
    """Rung 5 — entity-backed ownership check for one role."""
    if g.user_role == role_name and g.user_id != expected_id:
        raise_err("ERR_NOT_RESOURCE_OWNER")
