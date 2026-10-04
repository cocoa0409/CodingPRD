"""Authentication, authorization, and RetailerBuyer scope (PRD §2.1, §2.9).

Pipeline priorities 1-3:
  1. both headers present and role recognized -> ERR_UNAUTHENTICATED (401)
  2. role appears in the endpoint's role list -> ERR_FORBIDDEN (403)
  3. RetailerBuyer: X-User-ID equals the retailer_id of the plan that owns
     the target resource -> ERR_RETAILER_SCOPE_MISMATCH (403)
"""

from flask import request

from errors import err

ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_MANUFACTURER_PLANNER = "ManufacturerPlanner"
ROLE_RETAILER_BUYER = "RetailerBuyer"
ROLE_CATEGORY_ADVISOR = "CategoryAdvisor"
ROLE_SUPPLY_CHAIN_PLANNER = "SupplyChainPlanner"
ROLE_FINANCE_ANALYST = "FinanceAnalyst"

ALL_ROLES = [
    ROLE_PLATFORM_ADMIN,
    ROLE_MANUFACTURER_PLANNER,
    ROLE_RETAILER_BUYER,
    ROLE_CATEGORY_ADVISOR,
    ROLE_SUPPLY_CHAIN_PLANNER,
    ROLE_FINANCE_ANALYST,
]


def authenticate():
    """Priority 1. Returns (user_id, role)."""
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if uid is None or role is None or role not in ALL_ROLES:
        err("ERR_UNAUTHENTICATED", "missing or unrecognized authentication headers")
    return uid, role


def authorize(role, allowed):
    """Priority 2."""
    if role not in allowed:
        err("ERR_FORBIDDEN", "role " + role + " is not permitted on this endpoint")


def scope_plan(uid, role, plan):
    """Priority 3 (RetailerBuyer scope) against a resolved plan.

    Only fires when the acting role is RetailerBuyer and the owning plan
    resolved; an unresolvable chain falls through to the existence checks.
    """
    if role == ROLE_RETAILER_BUYER and plan is not None and plan["retailer_id"] != uid:
        err("ERR_RETAILER_SCOPE_MISMATCH", "resource belongs to a different retailer")


def rb_can_see(uid, role, plan):
    """Read-side visibility for lists: a RetailerBuyer sees only its own
    retailer's data (PRD §2.1)."""
    return role != ROLE_RETAILER_BUYER or plan["retailer_id"] == uid
