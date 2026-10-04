"""Authentication and role authorization (PRD sections 2.1, 2.9)."""
from flask import request

from errors import fail

ROLES = {
    "PlatformAdmin",
    "OriginationMerchandiser",
    "Farmer",
    "CrushTrader",
    "RiskManager",
    "PlantScheduler",
    "LogisticsCoordinator",
    "ProductMerchandiser",
    "CommercialBuyer",
    "SustainabilityAuditor",
}

ENTITY_BACKED = {"Farmer", "CommercialBuyer"}


def caller():
    """Priority 1: X-User-Role must be present and name a declared role."""
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES:
        fail("ERR_UNAUTHENTICATED",
             "X-User-Role header missing or not a declared role")
    return request.headers.get("X-User-ID"), role


def require_roles(*allowed):
    """Priority 1 then priority 2 (role permitted on the endpoint)."""
    uid, role = caller()
    if role not in allowed:
        fail("ERR_FORBIDDEN", "role %s is not permitted on this endpoint" % role)
    return uid, role
