"""Auth middleware: header extraction, role checking."""
from functools import wraps
from flask import request
from errors import raise_err

ROLES = {
    "OpsAdmin", "PurchasingManager", "LogisticsCoordinator", "ComplianceOfficer",
    "InventoryPlanner", "MarketingManager", "StoreClerk", "WarrantyAdjuster",
    "Customer",
}


def current_identity():
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise_err("ERR_UNAUTHENTICATED", "Missing or invalid X-User-ID / X-User-Role")
    return uid, role


def require_roles(*roles):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            uid, role = current_identity()
            if role not in roles:
                raise_err("ERR_FORBIDDEN", "Role not permitted for this endpoint")
            return fn(*args, **kwargs)
        return wrapper
    return deco
