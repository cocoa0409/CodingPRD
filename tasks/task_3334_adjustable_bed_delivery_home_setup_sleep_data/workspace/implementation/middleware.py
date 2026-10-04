"""Auth middleware (SCAFFOLD §1.4 priority 1-2, PRD §2.1, §1.7 RBAC)."""
from flask import request

from errors import err_unauthenticated, err_forbidden

KNOWN_ROLES = {
    "Anonymous",
    "PlatformAdmin",
    "SalesAssociate",
    "Customer",
    "DeliveryTechnician",
    "ServiceAgent",
    "FinanceAgent",
    "DeviceGateway",
}


def authenticate():
    """Validate auth headers. Returns (role, user_id). Raises ERR_UNAUTHENTICATED."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in KNOWN_ROLES:
        raise err_unauthenticated()
    if role != "Anonymous" and (user_id is None or user_id == ""):
        raise err_unauthenticated()
    return role, user_id


def require_roles(role, user_id, allowed_roles):
    if role not in allowed_roles:
        raise err_forbidden()


def check_customer_ownership(role, user_id, customer_id):
    """Customer role may only act on resources whose customer_id == X-User-ID."""
    if role == "Customer" and customer_id is not None and customer_id != user_id:
        raise err_forbidden()
