"""Pre-built role headers for every role in the PRD.

All roles are opaque with respect to persisted entities (PRD §2.1), so the
shared constants below are the canonical form. Buyer tier is pinned by the
`senior-` id prefix: use make_senior_buyer_headers() for discretion-gated
actions, and make_junior_buyer_headers() for the junior view.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "buyer_headers": build_user_headers("test-buyer-1", "Buyer"),
    "senior_buyer_headers": build_user_headers("senior-buyer-1", "Buyer"),
    "junior_buyer_headers": build_user_headers("junior-buyer-1", "Buyer"),
    "planning_lead_headers": build_user_headers("test-planning-lead-1", "PlanningLead"),
    "allocation_manager_headers": build_user_headers("test-allocation-manager-1", "AllocationManager"),
    "inventory_planner_headers": build_user_headers("test-inventory-planner-1", "InventoryPlanner"),
    "pricing_analyst_headers": build_user_headers("test-pricing-analyst-1", "PricingAnalyst"),
    "warehouse_clerk_headers": build_user_headers("test-warehouse-clerk-1", "WarehouseClerk"),
    "store_ops_lead_headers": build_user_headers("test-store-ops-lead-1", "StoreOpsLead"),
    "shrink_auditor_headers": build_user_headers("test-shrink-auditor-1", "ShrinkAuditor"),
}


def make_senior_buyer_headers(user_id: str = "senior-buyer-1") -> dict:
    """A Buyer whose id begins with 'senior-' is SENIOR tier (PRD §2.1)."""
    assert user_id.startswith("senior-"), "senior buyer ids must carry the 'senior-' prefix"
    return build_user_headers(user_id, "Buyer")


def make_junior_buyer_headers(user_id: str = "junior-buyer-1") -> dict:
    """Any Buyer id without the 'senior-' prefix is JUNIOR tier (PRD §2.1)."""
    assert not user_id.startswith("senior-"), "junior buyer ids must not carry the 'senior-' prefix"
    return build_user_headers(user_id, "Buyer")
