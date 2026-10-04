"""Authentication and role admission (gauntlet tiers 1-2, PRD §2.1).

Every request carries X-User-ID and X-User-Role. The first seven roles are
opaque (X-User-ID never compared against entity ids); Converter and Distributor
are entity-backed (X-User-ID is the acting partner record's id)."""

from flask import request

from errors import api_err

ALL_ROLES = [
    "PlatformAdmin",
    "ProductManager",
    "RegulatoryManager",
    "ChannelManager",
    "QualityAuditor",
    "TechnicalEngineer",
    "FinanceController",
    "Converter",
    "Distributor",
]

# GET endpoints are open to every one of the nine roles.
ANY_ROLE = list(ALL_ROLES)


def authenticate():
    """Tier 1: both headers present and non-empty, else ERR_UNAUTHENTICATED."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if user_id is None or not user_id.strip() or role is None or not role.strip():
        raise api_err("ERR_UNAUTHENTICATED",
                      "X-User-ID and X-User-Role headers are required")
    return user_id, role


def require_role(role, allowed):
    """Tier 2: the role must be admitted by the endpoint, else ERR_UNAUTHORIZED."""
    if role not in allowed:
        raise api_err("ERR_UNAUTHORIZED",
                      "Role %s is not permitted for this endpoint" % role)
