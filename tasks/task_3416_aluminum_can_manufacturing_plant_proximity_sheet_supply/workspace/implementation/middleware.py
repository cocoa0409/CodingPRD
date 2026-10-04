"""Authentication and authorization helpers (PRD section 2.1).

Gate 1: X-User-ID and X-User-Role present; role is one of the five declared
roles. Gate 2: role permitted for the endpoint, plus the CustomerPlanner
entity-backed ownership rule (X-User-ID is the acting Customer's id).
"""
from flask import request

from errors import ApiError, ERR_UNAUTHENTICATED, ERR_UNAUTHORIZED

ROLES = {"PlatformAdmin", "PlantManager", "LineScheduler", "CustomerPlanner", "QualityEngineer"}


def actor():
    """Gate 1 (authentication). Returns (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError(
            ERR_UNAUTHENTICATED[0], ERR_UNAUTHENTICATED[1],
            "Missing X-User-ID / X-User-Role headers, or unknown X-User-Role value.",
        )
    return user_id, role


def require_role(role, allowed):
    """Gate 2 (role permission for the endpoint)."""
    if role not in allowed:
        raise ApiError(
            ERR_UNAUTHORIZED[0], ERR_UNAUTHORIZED[1],
            "Role %s is not permitted for this endpoint." % role,
        )


def require_customer_owner(user_id, customer_id):
    """Gate 2 (CustomerPlanner ownership: X-User-ID must equal the customer id)."""
    if user_id != customer_id:
        raise ApiError(
            ERR_UNAUTHORIZED[0], ERR_UNAUTHORIZED[1],
            "CustomerPlanner may act only for its own customer.",
        )
