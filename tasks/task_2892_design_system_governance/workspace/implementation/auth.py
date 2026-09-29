"""Authentication, RBAC and ownership enforcement (PRD 2.1, 2.8 rules 1/2/6)."""

from functools import wraps

from flask import g, request

import errors
from errors import fail

SYSTEM_ADMIN = "SystemAdmin"
DESIGN_SYSTEM_LEAD = "DesignSystemLead"
DESIGN_CRITIQUE_REVIEWER = "DesignCritiqueReviewer"
ENGINEERING_REVIEWER = "EngineeringReviewer"
CONTRIBUTING_TEAM = "ContributingTeam"

ALL_ROLES = (
    SYSTEM_ADMIN,
    DESIGN_SYSTEM_LEAD,
    DESIGN_CRITIQUE_REVIEWER,
    ENGINEERING_REVIEWER,
    CONTRIBUTING_TEAM,
)


def _header(name):
    raw = request.headers.get(name)
    if raw is None:
        return None
    if raw.strip() == "":
        return None
    return raw


def require_roles(*allowed):
    allowed_set = tuple(allowed) if allowed else ALL_ROLES

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user_id = _header("X-User-ID")
            user_role = _header("X-User-Role")
            if user_id is None or user_role is None:
                fail(errors.ERR_UNAUTHENTICATED)
            if user_role not in ALL_ROLES or user_role not in allowed_set:
                fail(errors.ERR_UNAUTHORIZED)
            g.user_id = user_id
            g.user_role = user_role
            return view(*args, **kwargs)

        return wrapper

    return decorator


def clock_roles(view):
    """The logical-clock capability tolerates absent/blank headers (PRD 2.1)."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        user_id = _header("X-User-ID")
        user_role = _header("X-User-Role")
        if user_role is not None and user_role != SYSTEM_ADMIN:
            fail(errors.ERR_UNAUTHORIZED)
        g.user_id = user_id
        g.user_role = user_role or SYSTEM_ADMIN
        return view(*args, **kwargs)

    return wrapper


def is_contributing_team():
    return getattr(g, "user_role", None) == CONTRIBUTING_TEAM


def actor_id():
    return getattr(g, "user_id", None)


def ensure_owner(team_id):
    """PRD 2.8 rule 6: a ContributingTeam may only act on its own resources."""
    if is_contributing_team() and actor_id() != team_id:
        fail(errors.ERR_NOT_RESOURCE_OWNER)
