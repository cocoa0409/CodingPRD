"""Auth / RBAC (PRD §2.1, §2.8 steps 1-3) and request serialization lock."""

import functools
import threading

from flask import request

from errors import fail

# The six declared roles, spelled exactly as in PRD §2.1.
ROLES = {
    "PortfolioManager",
    "BrandManager",
    "PlantDirector",
    "RetailerBuyer",
    "SupplyChainPlanner",
    "FinanceController",
}

ALL_ROLES = [
    "PortfolioManager",
    "BrandManager",
    "PlantDirector",
    "RetailerBuyer",
    "SupplyChainPlanner",
    "FinanceController",
]

# A single global lock serializes all request handling, keeping the
# check-then-act validation pipelines atomic even under threaded=True.
GLOBAL_LOCK = threading.RLock()


def synchronized(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with GLOBAL_LOCK:
            return fn(*args, **kwargs)

    return wrapper


def authenticate():
    """Validation precedence steps 1-2. Returns (user_id, role)."""
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        fail("ERR_MISSING_ROLE",
             "X-User-Role header absent or not one of the six declared roles")
    user_id = request.headers.get("X-User-ID")
    if user_id is None or user_id == "":
        fail("ERR_MISSING_USER_ID", "X-User-ID header absent or empty")
    return user_id, role


def require_role(role, allowed):
    """Validation precedence step 3 (ERR_FORBIDDEN_ROLE)."""
    if role not in allowed:
        fail("ERR_FORBIDDEN_ROLE",
             f"role {role} is not authorized for this endpoint")


def guard(allowed_roles):
    """Steps 1-3 combined. Returns the caller's X-User-ID."""
    user_id, role = authenticate()
    require_role(role, allowed_roles)
    return user_id
