"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for non-ownership tests. For
# Dealer (entity-backed by Dealer) the shared constant is a fallback only;
# ownership-gated calls must use make_dealer_headers with the acting dealer id.
TEST_USERS = {
    "allocator_headers": build_user_headers("test-allocator-1", "RegionalAllocator"),
    "dealer_headers": build_user_headers("test-dealer-1", "Dealer"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "ProductionScheduler"),
    "logistics_headers": build_user_headers("test-logistics-1", "LogisticsCoordinator"),
    "commodity_manager_headers": build_user_headers("test-commodity-1", "CommodityManager"),
}


def make_dealer_headers(dealer_id: str) -> dict:
    """For Dealer (entity-backed by Dealer): X-User-ID must equal the acting
    dealer's id whenever the call is ownership-gated (order entry, trades,
    appeals, own-order cancel)."""
    return build_user_headers(dealer_id, "Dealer")
