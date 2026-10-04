"""Auth header extraction and role checking (validation priorities 1 and 2)."""

from flask import request

from response import ApiError, Err

ROLES = (
    "ChainAdmin",
    "StoreManager",
    "CreditAnalyst",
    "SalesAssociate",
    "CustomerService",
    "Customer",
)


def current_identity():
    """Priority 1: both headers present and the role declared."""
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or not user_id or role not in ROLES:
        raise ApiError(Err.UNAUTHENTICATED)
    return user_id, role


def authorize(role, allowed):
    """Priority 2: the acting role is permitted for this operation."""
    if role not in allowed:
        raise ApiError(Err.UNAUTHORIZED)


def guard(allowed):
    """Return (user_id, role) after both auth layers pass."""
    user_id, role = current_identity()
    authorize(role, allowed)
    return user_id, role


def require_owner(user_id, role, resource, field="customer_id"):
    """Priority 12: the acting customer must own the named resource.

    Only the entity-backed Customer role is subject to the ownership check;
    the five opaque operator roles never make an ownership decision.
    """
    if role == "Customer" and resource.get(field) != user_id:
        raise ApiError(Err.NOT_RESOURCE_OWNER)