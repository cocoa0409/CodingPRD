"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership. For Subscriber (entity-backed by SubscriberAccount) the shared
# constant is a fallback only; ownership-gated calls must use
# make_subscriber_headers with the actual account id.
TEST_USERS = {
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    "subscriber_headers": build_user_headers("test-subscriber-1", "Subscriber"),
    "support_headers": build_user_headers("test-support-1", "Support"),
    "distributor_ops_headers": build_user_headers("test-distributor-ops-1", "DistributorOps"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
}


def make_subscriber_headers(subscriber_account_id: str) -> dict:
    """For Subscriber (entity-backed by SubscriberAccount): X-User-ID must equal
    the acting account's id whenever the call is ownership-gated."""
    return build_user_headers(subscriber_account_id, "Subscriber")
