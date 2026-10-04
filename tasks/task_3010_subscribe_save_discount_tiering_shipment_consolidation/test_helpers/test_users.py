"""Pre-built role headers for every role in the PRD (§2.1).

The Customer role is entity-backed: ownership checks compare the resource's
owning-customer chain against X-User-ID, so any ownership-gated call MUST use
make_customer_headers(customer["id"]) with the real Customer id. The shared
constant below is a fallback for tests that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed: shared constant is a fallback for non-ownership tests only.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    # opaque roles: shared constant is the canonical form.
    "support_agent_headers": build_user_headers("test-support-agent-1", "SupportAgent"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
}


def make_customer_headers(user_id: str) -> dict:
    """For the Customer role. Pass the actual Customer.id as user_id whenever
    the call is ownership-gated (subscriptions, plans, lines, claims, offers)."""
    return build_user_headers(user_id, "Customer")


def make_support_agent_headers(user_id: str = "support-agent-1") -> dict:
    return build_user_headers(user_id, "SupportAgent")


def make_platform_admin_headers(user_id: str = "platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")
