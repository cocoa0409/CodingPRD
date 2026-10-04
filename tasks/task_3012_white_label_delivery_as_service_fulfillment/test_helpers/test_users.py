"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. Merchant and Courier are entity-backed: use the per-instance
# builders below whenever a call is ownership-gated.
TEST_USERS = {
    # entity_backed:Merchant — fallback for non-ownership tests only.
    "merchant_headers": build_user_headers("test-merchant-1", "Merchant"),
    # entity_backed:Courier — fallback for non-ownership tests only.
    "courier_headers": build_user_headers("test-courier-1", "Courier"),
    # opaque roles — canonical shared form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "support_agent_headers": build_user_headers("test-support-1", "SupportAgent"),
}


def make_merchant_headers(merchant_id: str) -> dict:
    """For Merchant (entity-backed): pass the actual Merchant.id whenever the
    call is ownership-gated."""
    return build_user_headers(merchant_id, "Merchant")


def make_courier_headers(courier_id: str) -> dict:
    """For Courier (entity-backed): pass the actual Courier.id whenever the
    call is ownership-gated."""
    return build_user_headers(courier_id, "Courier")


def make_platform_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_support_agent_headers(user_id: str = "test-support-1") -> dict:
    return build_user_headers(user_id, "SupportAgent")
