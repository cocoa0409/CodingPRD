"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles use shared constants. The Customer role is entity-backed, so
ownership-gated calls must use make_customer_headers(<customer id>).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "ops_admin_headers": build_user_headers("test-ops-admin-1", "OpsAdmin"),
    "purchasing_manager_headers": build_user_headers("test-pm-1", "PurchasingManager"),
    "logistics_coordinator_headers": build_user_headers("test-lc-1", "LogisticsCoordinator"),
    "compliance_officer_headers": build_user_headers("test-co-1", "ComplianceOfficer"),
    "inventory_planner_headers": build_user_headers("test-ip-1", "InventoryPlanner"),
    "marketing_manager_headers": build_user_headers("test-mm-1", "MarketingManager"),
    "store_clerk_headers": build_user_headers("test-sc-1", "StoreClerk"),
    "warranty_adjuster_headers": build_user_headers("test-wa-1", "WarrantyAdjuster"),
    # entity_backed:Customer — shared constant ONLY for non-ownership tests.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role (entity-backed): pass the actual Customer.id as
    user_id whenever the call is ownership-gated (appeal, self-service)."""
    return build_user_headers(user_id, "Customer")
