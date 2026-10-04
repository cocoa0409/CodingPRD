"""Auth middleware: header extraction, role checking (PRD §2.1)."""
from flask import request

from errors import forbidden, unauthenticated

DECLARED_ROLES = {
    "Anonymous",
    "RegionalAllocator",
    "Dealer",
    "ProductionScheduler",
    "LogisticsCoordinator",
    "CommodityManager",
}


def auth_context(allowed_roles):
    """Validate auth headers + role membership. Returns (role, user_id)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in DECLARED_ROLES:
        raise unauthenticated()
    if role not in allowed_roles:
        raise forbidden()
    return role, user_id


def require_dealer_owns(user_id: str, owner_id):
    """Entity-backed identity: Dealer role may only act on its own dealer_id."""
    if owner_id is None or str(owner_id) != str(user_id):
        raise forbidden()
