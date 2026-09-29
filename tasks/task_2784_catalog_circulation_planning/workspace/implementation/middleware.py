"""Auth header extraction and role gating.

Identity travels in `X-User-ID`; the caller's single role travels in
`X-User-Role`.  Authentication is checked before authorisation, and both are
checked before any path identifier is resolved.
"""

from flask import request

from errors import ApiError

PLATFORM_ADMIN = "PlatformAdmin"
CIRCULATION_PLANNER = "CirculationPlanner"
CIRCULATION_DIRECTOR = "CirculationDirector"
LIST_BROKER = "ListBroker"
MARKETING_ANALYST = "MarketingAnalyst"

ALL_ROLES = (
    PLATFORM_ADMIN,
    CIRCULATION_PLANNER,
    CIRCULATION_DIRECTOR,
    LIST_BROKER,
    MARKETING_ANALYST,
)

# Everyone except the list broker, whose window is limited to the list-rental and
# merge-purge surface plus the general catalogue reads.
NO_BROKER = (
    PLATFORM_ADMIN,
    CIRCULATION_PLANNER,
    CIRCULATION_DIRECTOR,
    MARKETING_ANALYST,
)

ADMIN_PLANNER = (PLATFORM_ADMIN, CIRCULATION_PLANNER)
ADMIN_PLANNER_BROKER = (PLATFORM_ADMIN, CIRCULATION_PLANNER, LIST_BROKER)
ADMIN_PLANNER_DIRECTOR = (PLATFORM_ADMIN, CIRCULATION_PLANNER, CIRCULATION_DIRECTOR)
ADMIN_DIRECTOR = (PLATFORM_ADMIN, CIRCULATION_DIRECTOR)
ADMIN_ANALYST = (PLATFORM_ADMIN, MARKETING_ANALYST)
ADMIN_PLANNER_ANALYST = (PLATFORM_ADMIN, CIRCULATION_PLANNER, MARKETING_ANALYST)


def auth(*allowed_roles):
    """Return (user_id, role) or raise the appropriate auth error."""
    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id.strip() == "":
        raise ApiError("ERR_UNAUTHENTICATED")
    role = request.headers.get("X-User-Role")
    if role is None or role.strip() == "":
        raise ApiError("ERR_FORBIDDEN_ROLE")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN_ROLE")
    return user_id, role
