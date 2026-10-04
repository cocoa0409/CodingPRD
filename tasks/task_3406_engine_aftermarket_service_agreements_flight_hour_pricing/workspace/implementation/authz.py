"""Authentication and authorization (validation tiers 1-2, PRD 2.1/2.8).

Headers: X-User-ID and X-User-Role. Roles: PlatformAdmin, ContractManager,
Operator, ShopPlanner, FinanceController. For Operator callers, X-User-ID is the
id of the acting Operator entity and ownership is resolved through the engine
chain (PRD 2.1).
"""
from flask import request

from errors import api_err

ROLES = {"PlatformAdmin", "ContractManager", "Operator", "ShopPlanner", "FinanceController"}


def current_caller():
    """Tier 1: both headers present and the role is a declared role."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise api_err("ERR_UNAUTHENTICATED", "X-User-ID and a declared X-User-Role are required")
    return uid, role


def require_roles(*roles):
    """Tiers 1+2: authenticated, and the role is allowed on the endpoint."""
    uid, role = current_caller()
    if role not in roles:
        raise api_err("ERR_FORBIDDEN", "role {} may not perform this operation".format(role))
    return uid, role


def check_operator_ownership(uid, role, owner_operator_id):
    """Tier 2 ownership: an Operator caller must own the target resource
    (ownership chain resolved by the caller through the engine)."""
    if role == "Operator" and uid != owner_operator_id:
        raise api_err("ERR_FORBIDDEN", "operator does not own the target resource")
