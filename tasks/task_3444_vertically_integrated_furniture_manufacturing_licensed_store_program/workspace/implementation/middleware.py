"""Auth (stage 1), role authorization (stage 3), ownership scoping (stage 4)."""
from flask import request

from constants import ROLES
from errors import err


def auth():
    """Stage 1: X-User-ID + X-User-Role present and role declared -> (uid, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", "missing or unknown X-User-Role / X-User-ID headers")
    return uid, role


def require_role(role, allowed):
    """Stage 3: acting role must be in the endpoint's roles list."""
    if role not in allowed:
        err("ERR_FORBIDDEN_ROLE", "role %s may not call this endpoint" % role)


def require_order_owner(uid, role, order):
    """Stage 4: entity-backed roles must own the order's buyer FK."""
    if role == "LicenseeManager":
        if uid != order.get("licensee_id"):
            err("ERR_NOT_RESOURCE_OWNER", "X-User-ID does not match the order's licensee_id")
    elif role == "WholesaleBuyer":
        if uid != order.get("retail_account_id"):
            err("ERR_NOT_RESOURCE_OWNER", "X-User-ID does not match the order's retail_account_id")


def require_licensee_owner(uid, role, licensee_id):
    """Stage 4 for LicenseeManager-scoped resources (appointments, claims)."""
    if role == "LicenseeManager" and uid != licensee_id:
        err("ERR_NOT_RESOURCE_OWNER", "X-User-ID does not match the resource's licensee_id")
