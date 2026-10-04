"""Auth middleware: header extraction, role validation, RBAC helpers."""
from flask import request

from errors import err_unauthenticated, err_forbidden

ROLES = {"Athlete", "Moderator", "PlatformAdmin"}


def get_auth():
    """Return (user_id, role) or raise ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err_unauthenticated()
    return user_id, role


def require_roles(*roles):
    """Ensure the caller's role is one of the permitted roles (RBAC rung 2)."""
    user_id, role = get_auth()
    if role not in roles:
        raise err_forbidden()
    return user_id, role


def is_privileged(role):
    return role in ("PlatformAdmin", "Moderator")


def check_self_or_admin(user_id, role, target_athlete_id):
    """Athlete callers must act on their own resources; admin/moderator bypass."""
    if role == "Athlete" and user_id != target_athlete_id:
        raise err_forbidden()


def check_athlete_self(user_id, role, target_athlete_id):
    """Strict self-only check (e.g. deletion); only Athlete role with matching id."""
    if role != "Athlete" or user_id != target_athlete_id:
        raise err_forbidden()
