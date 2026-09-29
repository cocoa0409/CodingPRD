"""Authentication, authorization and resource-ownership checks.

PRD section 2.1: every request carries X-User-ID and X-User-Role.  Header names are
matched case-insensitively (Flask's header mapping already does that).

Bands 1, 2 and 4 of the section 2.6 precedence ladder live here.
"""

import functools

from flask import g, request

from errors import fail

ROLES = (
    "LeagueAdmin",
    "GeneralManager",
    "PlayerAgent",
    "Scout",
    "CoachingStaff",
    "PerformanceSupport",
    "SponsorshipManager",
    "FinanceOfficer",
    "OpsManager",
    "GuardianRepresentative",
)

# PRD section 2.1 -- entity-backed roles.
ORG_BACKED_ROLES = frozenset(["GeneralManager", "SponsorshipManager", "OpsManager"])
PLAYER_BACKED_ROLES = frozenset(["PlayerAgent", "GuardianRepresentative"])


def authenticate():
    """Band 1 then band 2 (the role-name recognition half)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or user_id == "" or role is None or role == "":
        fail("ERR_UNAUTHENTICATED", "Both X-User-ID and X-User-Role headers are required.")
    g.user_id = user_id
    g.user_role = role
    if role not in ROLES:
        fail("ERR_UNAUTHORIZED", "Unrecognised role '%s'." % role)
    return user_id, role


def endpoint(roles):
    """Bind an endpoint's authorised role list (PRD section 4) to its handler."""
    allowed = frozenset(roles)

    def decorator(view):
        @functools.wraps(view)
        def wrapper(*args, **kwargs):
            user_id, role = authenticate()
            if role not in allowed:
                fail("ERR_UNAUTHORIZED", "Role '%s' is not authorised for this endpoint." % role)
            return view(*args, **kwargs)

        return wrapper

    return decorator


def caller():
    return g.get("user_id"), g.get("user_role")


def require_org_owner(*organization_ids):
    """Band 4 for the three Organization-backed roles."""
    user_id, role = caller()
    if role not in ORG_BACKED_ROLES:
        return
    candidates = [oid for oid in organization_ids if oid is not None]
    if not candidates:
        return
    if user_id not in candidates:
        fail(
            "ERR_NOT_RESOURCE_OWNER",
            "Role '%s' may only act on its own organization's resources." % role,
        )


def require_player_owner(*player_ids):
    """Band 4 for the two Player-backed roles."""
    user_id, role = caller()
    if role not in PLAYER_BACKED_ROLES:
        return
    candidates = [pid for pid in player_ids if pid is not None]
    if not candidates:
        return
    if user_id not in candidates:
        fail(
            "ERR_NOT_RESOURCE_OWNER",
            "Role '%s' may only act on its own player's resources." % role,
        )


def require_owner(organization_ids=(), player_ids=()):
    require_org_owner(*organization_ids)
    require_player_owner(*player_ids)
