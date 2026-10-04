"""Auth header extraction and role checking (PRD §2.1, SCAFFOLD §1.7)."""

from flask import request

from errors import unauthenticated, unauthorized

DECLARED_ROLES = {
    "SupplyChainDirector",
    "CommissaryPlanner",
    "QualityAuditor",
    "RealEstatePlanner",
    "StoreManager",
    "Associate",
    "HRDirector",
}

ENTITY_BACKED_ROLES = {"StoreManager", "Associate"}


def caller():
    """Return (user_id, role). Raises ERR_UNAUTHENTICATED if role header missing/invalid."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in DECLARED_ROLES:
        raise unauthenticated("X-User-Role header missing or names an undeclared role")
    return request.headers.get("X-User-ID"), role


def require_roles(*roles):
    """Auth (tier 1) + authorization (tier 2). Returns (user_id, role)."""
    user_id, role = caller()
    if role not in roles:
        raise unauthorized("Role %s not permitted for this endpoint" % role)
    return user_id, role
