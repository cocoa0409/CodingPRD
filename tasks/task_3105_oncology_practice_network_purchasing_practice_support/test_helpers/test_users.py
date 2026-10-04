"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership. PracticeAdmin is entity_backed:Practice, so the shared constant is
# only a fallback for calls that are not ownership-gated.
TEST_USERS = {
    "network_admin_headers": build_user_headers("test-network-admin-1", "NetworkAdmin"),
    "practice_admin_headers": build_user_headers("test-practice-admin-1", "PracticeAdmin"),
    "revenue_cycle_manager_headers": build_user_headers("test-rcm-1", "RevenueCycleManager"),
    "payer_adjudicator_headers": build_user_headers("test-payer-adj-1", "PayerAdjudicator"),
    "network_analyst_headers": build_user_headers("test-analyst-1", "NetworkAnalyst"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
}


def make_practice_admin_headers(user_id: str) -> dict:
    """For PracticeAdmin (entity_backed:Practice). Pass the actual Practice.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "PracticeAdmin")


def make_network_admin_headers(user_id: str = "test-network-admin-1") -> dict:
    """NetworkAdmin is opaque; the user id is recorded but never compared to an
    entity id."""
    return build_user_headers(user_id, "NetworkAdmin")


def make_revenue_cycle_manager_headers(user_id: str = "test-rcm-1") -> dict:
    return build_user_headers(user_id, "RevenueCycleManager")


def make_payer_adjudicator_headers(user_id: str = "test-payer-adj-1") -> dict:
    return build_user_headers(user_id, "PayerAdjudicator")


def make_network_analyst_headers(user_id: str = "test-analyst-1") -> dict:
    return build_user_headers(user_id, "NetworkAnalyst")


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_headers(user_id: str, role: str) -> dict:
    """Generic builder — used by tests that need an unnamed or unknown role."""
    return build_user_headers(user_id, role)