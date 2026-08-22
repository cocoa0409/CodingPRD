"""Header based authentication and RBAC (PRD 2.1, judged first per PRD 2.5)."""

from functools import wraps

from flask import g, request

from errors import ApiError

ROLES = ("MusicHouseProducer", "ClientRep", "Composer", "RightsAdmin", "AFMSteward")

ALL_ROLES = list(ROLES)


def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", "Valid X-User-ID and X-User-Role headers are required.")
    g.user_id = user_id
    g.role = role


def authorize(roles):
    if g.role not in roles:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Role %s may not perform this operation." % g.role)


def endpoint(roles):
    """Judgement steps 1 and 2 of PRD 2.5, on every endpoint including reads."""

    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            authenticate()
            authorize(roles)
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def require_project_owner(project):
    """Ownership: a ClientRep acts only on its own engagements (PRD 2.1)."""
    if g.role == "ClientRep" and g.user_id != project.get("client_id"):
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Acting client does not own this engagement.")


def require_demo_owner(demo):
    """Ownership: a Composer acts only on its own demos (PRD 2.1)."""
    if g.role == "Composer" and g.user_id != demo.get("composer_id"):
        raise ApiError("ERR_NOT_RESOURCE_OWNER", "Acting composer does not own this demo.")
