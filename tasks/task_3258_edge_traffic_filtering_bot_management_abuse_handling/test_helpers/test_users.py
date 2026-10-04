"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise
# ownership. The ZoneAdmin shared constant is a fallback only; ownership-gated
# calls must use make_zone_admin_headers(account_id).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "zone_admin_headers": build_user_headers("test-zone-admin-orphan", "ZoneAdmin"),
    "trust_safety_headers": build_user_headers("test-trust-safety-1", "TrustSafetyAnalyst"),
    "network_planner_headers": build_user_headers("test-network-planner-1", "NetworkPlanner"),
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
}


def make_zone_admin_headers(user_id: str) -> dict:
    """For ZoneAdmin, whose X-User-ID must equal the acting Account's id.
    Pass the actual Account.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "ZoneAdmin")


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_trust_safety_headers(user_id: str = "test-trust-safety-1") -> dict:
    return build_user_headers(user_id, "TrustSafetyAnalyst")


def make_network_planner_headers(user_id: str = "test-network-planner-1") -> dict:
    return build_user_headers(user_id, "NetworkPlanner")


def make_anonymous_headers(user_id: str = "test-anonymous-1") -> dict:
    return build_user_headers(user_id, "Anonymous")
