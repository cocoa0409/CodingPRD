"""Auth middleware: X-User-ID + X-User-Role validation per PRD §2.1."""
from flask import request

from errors import ApiError, ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER, ERR_FORBIDDEN

ROLES = {
    "ContractManager",
    "TerminalOperator",
    "EquipmentController",
    "BillingAgent",
    "CreditSupervisor",
    "CreditDirector",
    "CustomerRep",
}


def get_auth():
    """Return (user_id, role). Raises ApiError if headers missing/invalid."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER,
            400,
            "X-User-ID and X-User-Role headers required with a declared role",
        )
    return user_id, role


def require_roles(*allowed):
    user_id, role = get_auth()
    if role not in allowed:
        raise ApiError(ERR_FORBIDDEN, 403, f"Role {role} not permitted for this operation")
    return user_id, role
