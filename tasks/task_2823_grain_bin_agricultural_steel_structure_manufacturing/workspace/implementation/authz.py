"""Auth header extraction and role authorization (PRD 2.1, ladder steps 1-2)."""
from flask import request

from errors import ApiError

ROLES = (
    "PlantAdmin",
    "DesignEngineer",
    "SealingEngineer",
    "ProductionPlanner",
    "DealerPrincipal",
    "LogisticsCoordinator",
    "QualityInspector",
)

ALL_ROLES = ROLES


def authorize(allowed_roles):
    """Step 1: both headers present and the role is one of the seven.
    Step 2: the role appears in the endpoint's role list."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or role is None or user_id == "" or role == "":
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    if role not in ROLES:
        raise ApiError("ERR_MISSING_AUTH_HEADERS")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED_ROLE")
    return user_id, role
