"""Auth middleware: X-User-ID / X-User-Role extraction and RBAC checks."""
from flask import request

import errors as err
from errors import ApiError

ROLES = {
    "Buyer", "PlanningLead", "AllocationManager", "InventoryPlanner",
    "PricingAnalyst", "WarehouseClerk", "StoreOpsLead", "ShrinkAuditor",
}


def actor():
    """Authenticate the request (401) and return (user_id, role)."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise err.unauthenticated()
    return user_id, role


def require(roles):
    """Authenticate then authorize (403). Returns (user_id, role)."""
    user_id, role = actor()
    if role not in roles:
        raise err.unauthorized()
    return user_id, role


def is_senior_buyer(user_id, role):
    return role == "Buyer" and str(user_id).startswith("senior-")


def buyer_tier(user_id):
    return "SENIOR" if str(user_id).startswith("senior-") else "JUNIOR"


def enforce_discretion(lot, user_id, role, vendors):
    """403 when a junior Buyer touches a CONFIDENTIAL/QUIET vendor lot."""
    if role != "Buyer":
        return
    vendor = vendors.get(lot["vendor_id"])
    if vendor and vendor["discretion_level"] in ("CONFIDENTIAL", "QUIET") \
            and not is_senior_buyer(user_id, role):
        raise ApiError("ERR_VENDOR_DISCRETION",
                       "junior buyer may not act on a CONFIDENTIAL/QUIET vendor lot")
