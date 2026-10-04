"""Pre-built role headers for every role in the PRD.

The Customer role is entity-backed: X-User-ID must equal the Customer entity id
for any ownership-gated call. Use make_customer_headers(customer_id) for those;
the shared constant is a fallback for tests that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are the canonical form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "ops_manager_headers": build_user_headers("test-ops-1", "OpsManager"),
    "hauler_agent_headers": build_user_headers("test-hauler-1", "HaulerAgent"),
    # Entity-backed role: fallback only for non-ownership tests.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(customer_id: str) -> dict:
    """Customer headers bound to a real Customer entity id (ownership-gated calls)."""
    return build_user_headers(customer_id, "Customer")
