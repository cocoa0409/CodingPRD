"""Auth header extraction and role checks (PRD 2.1, validation precedence 1-2)."""
from flask import request

from errors import raise_error, ERR_UNAUTHENTICATED, ERR_FORBIDDEN

ALL_ROLES = {
    "Homeowner",
    "WarrantyRep",
    "TradePartner",
    "WarrantyManager",
    "FinanceAdmin",
    "WarrantyAdministrator",
}


def get_caller():
    """Priority 1: X-User-ID and X-User-Role present; role is a declared role."""
    user_id = request.headers.get("X-User-ID", "").strip()
    role = request.headers.get("X-User-Role", "").strip()
    if not user_id or not role or role not in ALL_ROLES:
        raise_error(
            ERR_UNAUTHENTICATED,
            "X-User-ID and X-User-Role headers must be present and the role must be declared",
        )
    return user_id, role


def require_role(role: str, allowed_roles):
    """Priority 2: the acting role is listed in the endpoint's roles."""
    if role not in allowed_roles:
        raise_error(ERR_FORBIDDEN, f"role {role} is not authorized for this endpoint")
