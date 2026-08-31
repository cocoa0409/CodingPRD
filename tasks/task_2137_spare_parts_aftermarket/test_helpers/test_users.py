"""Pre-built role headers for every role in the PRD."""

from prd_bench_local_runner.testing import build_user_headers

# Operator identifiers.  For AftermarketPlanner, InventoryController,
# PricingAnalyst and PlatformAdmin the X-User-ID is an opaque operator
# identifier that is never compared to any entity id (PRD section 2.1).
PLANNER_USER_ID = "planner-1"
CONTROLLER_USER_ID = "ctrl-1"
PRICING_USER_ID = "pricing-1"
ADMIN_USER_ID = "admin-1"

# Shared constants.  Safe for the four opaque roles.  The DealerUser entry is a
# fallback only for requests that never reach an ownership check.
TEST_USERS = {
    "planner_headers": build_user_headers(PLANNER_USER_ID, "AftermarketPlanner"),
    "controller_headers": build_user_headers(CONTROLLER_USER_ID, "InventoryController"),
    "pricing_headers": build_user_headers(PRICING_USER_ID, "PricingAnalyst"),
    "admin_headers": build_user_headers(ADMIN_USER_ID, "PlatformAdmin"),
    "dealer_headers": build_user_headers("test-dealer-1", "DealerUser"),
}


def make_dealer_headers(dealer_id: str) -> dict:
    """For DealerUser.  X-User-ID must be the acting Dealer's own id, because
    every dealer-scoped operation compares it to the dealer_id reachable from
    the target resource (PRD section 2.1)."""
    return build_user_headers(dealer_id, "DealerUser")


def make_planner_headers(user_id: str) -> dict:
    """AftermarketPlanner acting under a specific operator identifier."""
    return build_user_headers(user_id, "AftermarketPlanner")


def make_controller_headers(user_id: str) -> dict:
    """InventoryController acting under a specific operator identifier."""
    return build_user_headers(user_id, "InventoryController")


def make_pricing_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PricingAnalyst")


def make_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
