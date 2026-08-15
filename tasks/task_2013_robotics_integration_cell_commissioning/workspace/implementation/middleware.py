"""Auth header extraction and role checking (PRD §2.1, §2.6 priorities 1-2)."""
from flask import request

from errors import ApiError, ERR_FORBIDDEN_ROLE, ERR_UNAUTHENTICATED

ROLE_PROJECT_ENGINEER = "ProjectEngineer"
ROLE_SAFETY_LEAD = "SafetyLead"
ROLE_CONTROLS_PROGRAMMER = "ControlsProgrammer"
ROLE_SITE_SUPERVISOR = "SiteSupervisor"
ROLE_TRAINER = "Trainer"
ROLE_SERVICE_MANAGER = "ServiceManager"
ROLE_FINANCE_ADMIN = "FinanceAdmin"

VALID_ROLES = frozenset({
    ROLE_PROJECT_ENGINEER,
    ROLE_SAFETY_LEAD,
    ROLE_CONTROLS_PROGRAMMER,
    ROLE_SITE_SUPERVISOR,
    ROLE_TRAINER,
    ROLE_SERVICE_MANAGER,
    ROLE_FINANCE_ADMIN,
})


def authenticate(allowed_roles=None):
    """Validate X-User-ID / X-User-Role headers; enforce endpoint role list.

    Returns (user_id, role).
    """
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if (
        user_id is None
        or not isinstance(user_id, str)
        or user_id.strip() == ""
        or role is None
        or role not in VALID_ROLES
    ):
        raise ApiError(
            ERR_UNAUTHENTICATED,
            401,
            "Missing or invalid X-User-ID / X-User-Role headers",
        )
    if allowed_roles is not None and role not in allowed_roles:
        raise ApiError(
            ERR_FORBIDDEN_ROLE,
            403,
            f"Role '{role}' is not permitted for this endpoint",
        )
    return user_id, role
