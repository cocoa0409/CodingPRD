"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "SupplyChainAdmin"),
    "coordinator_headers": build_user_headers("test-coordinator-1", "RouteCoordinator"),
    "any_headers": build_user_headers("test-any-1", "Any"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "store_manager_headers": build_user_headers("test-store-manager-1", "StoreManager"),
}


def make_store_manager_headers(store_id: str) -> dict:
    """For StoreManager (entity_backed:Store). Pass the actual Store.id as store_id
    whenever the call is ownership-gated (PO create/submit/cancel, compliance reports)."""
    return build_user_headers(store_id, "StoreManager")
