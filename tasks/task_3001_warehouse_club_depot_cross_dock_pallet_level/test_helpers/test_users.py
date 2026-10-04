"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership. For VendorRep (entity-backed by Vendor) the shared constant is a
# fallback only; ownership-gated calls must use make_vendor_rep_headers with
# the actual vendor id.
TEST_USERS = {
    "regional_ops_headers": build_user_headers("test-regional-ops-1", "RegionalOps"),
    "category_manager_headers": build_user_headers("test-category-manager-1", "CategoryManager"),
    "depot_manager_headers": build_user_headers("test-depot-manager-1", "DepotManager"),
    "depot_planner_headers": build_user_headers("test-depot-planner-1", "DepotPlanner"),
    "membership_desk_headers": build_user_headers("test-membership-desk-1", "MembershipDesk"),
    "vendor_rep_headers": build_user_headers("test-vendor-rep-1", "VendorRep"),
}


def make_vendor_rep_headers(vendor_id: str) -> dict:
    """For VendorRep (entity-backed by Vendor): X-User-ID must equal the acting
    vendor's id whenever the call is ownership-gated (appointment booking and
    cancellation, chargeback appeal)."""
    return build_user_headers(vendor_id, "VendorRep")
