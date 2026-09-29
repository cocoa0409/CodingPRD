"""Authentication / RBAC (PRD 2.1)."""

from flask import request

from errors import ApiError

USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"

SALES_ENGINEER = "SalesEngineer"
CONTRACTS_ADMIN = "ContractsAdmin"
PLANT_SCHEDULER = "PlantScheduler"
QUALITY_INSPECTOR = "QualityInspector"
COMPLIANCE_OFFICER = "ComplianceOfficer"
DEALER_AGENT = "DealerAgent"

ROLES = (
    SALES_ENGINEER,
    CONTRACTS_ADMIN,
    PLANT_SCHEDULER,
    QUALITY_INSPECTOR,
    COMPLIANCE_OFFICER,
    DEALER_AGENT,
)


def authenticate():
    """Both headers must be present and the role must be one of the six."""
    user_id = request.headers.get(USER_ID_HEADER)
    role = request.headers.get(USER_ROLE_HEADER)
    if not user_id or not role:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    return user_id, role


def actor(*allowed):
    """Authenticate, then enforce role permission. No args => any role."""
    user_id, role = authenticate()
    if allowed and role not in allowed:
        raise ApiError("ERR_ROLE_NOT_PERMITTED")
    return user_id, role
