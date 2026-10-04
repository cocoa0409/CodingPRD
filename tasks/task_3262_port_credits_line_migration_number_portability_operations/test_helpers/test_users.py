"""Pre-built role headers for every role named by the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants.
# The four internal roles carry an opaque handle not tied to any persisted
# entity, so a shared constant is the canonical form for them. The Customer
# role is entity-backed on Account: the constant below is only a fallback for
# calls whose outcome does not depend on ownership, and every ownership-gated
# call MUST instead use make_customer_headers(account_id).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "customer_service_headers": build_user_headers("test-care-1", "CustomerService"),
    "credit_analyst_headers": build_user_headers("test-analyst-1", "CreditAnalyst"),
    "trade_in_inspector_headers": build_user_headers(
        "test-inspector-1", "TradeInInspector"
    ),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(account_id: str) -> dict:
    """For Customer (entity_backed:Account).

    Pass the actual Account.id as user_id whenever the call is ownership-gated,
    so the server's foreign-key comparison against X-User-ID succeeds.
    """
    return build_user_headers(account_id, "Customer")