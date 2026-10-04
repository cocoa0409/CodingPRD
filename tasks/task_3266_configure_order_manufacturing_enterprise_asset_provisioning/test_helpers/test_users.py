"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership. The CustomerUser shared constant is a fallback for non-ownership
# tests only; ownership-gated calls must use make_customer_user_headers(account_id).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "account_manager_headers": build_user_headers("test-account-manager-1", "AccountManager"),
    # entity_backed role: fallback for non-ownership tests only.
    "customer_user_headers": build_user_headers("test-customer-orphan", "CustomerUser"),
    "factory_ops_headers": build_user_headers("test-factory-ops-1", "FactoryOps"),
}


def make_customer_user_headers(user_id: str) -> dict:
    """For CustomerUser, whose X-User-ID must equal the acting CustomerAccount.id.
    Pass the actual account id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "CustomerUser")


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_account_manager_headers(user_id: str = "test-account-manager-1") -> dict:
    return build_user_headers(user_id, "AccountManager")


def make_factory_ops_headers(user_id: str = "test-factory-ops-1") -> dict:
    return build_user_headers(user_id, "FactoryOps")
