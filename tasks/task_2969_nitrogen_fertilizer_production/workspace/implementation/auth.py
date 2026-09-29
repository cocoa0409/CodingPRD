"""Rungs 1-3 of the rejection ladder: authentication, role vocabulary, authorisation."""
from flask import request

from errors import ApiError

REGULATORY_ADMIN = "RegulatoryAdmin"
PROCESS_ENGINEER = "ProcessEngineer"
SAFETY_OFFICER = "SafetyOfficer"
COMMERCIAL_MANAGER = "CommercialManager"
LOGISTICS_COORDINATOR = "LogisticsCoordinator"
TERMINAL_OPERATOR = "TerminalOperator"

ROLES = (
    REGULATORY_ADMIN,
    PROCESS_ENGINEER,
    SAFETY_OFFICER,
    COMMERCIAL_MANAGER,
    LOGISTICS_COORDINATOR,
    TERMINAL_OPERATOR,
)

# Every read endpoint is open to all six roles.
ALL_ROLES = ROLES


def actor(allowed):
    """Resolve the acting identity, or raise the first ladder violation."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or not str(user_id).strip() or not str(role).strip():
        raise ApiError("ERR_UNAUTHENTICATED")
    user_id = str(user_id)
    role = str(role)
    if role not in ROLES:
        raise ApiError("ERR_UNKNOWN_ROLE")
    if role not in allowed:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return {"user_id": user_id, "role": role}
