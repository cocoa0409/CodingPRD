"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "platform_headers": build_user_headers("test-platform-op-1", "PlatformBillingOperator"),
    "admin_headers": build_user_headers("test-org-admin-1", "OrgAdmin"),
    "finance_headers": build_user_headers("test-finance-analyst-1", "FinanceAnalyst"),
    # Fallback for non-ownership tests only; ownership-gated calls MUST use the builder.
    "manager_headers": build_user_headers("test-account-manager-1", "LinkedAccountManager"),
}


def make_platform_headers(user_id: str = "test-platform-op-1") -> dict:
    """For PlatformBillingOperator (opaque identity)."""
    return build_user_headers(user_id, "PlatformBillingOperator")


def make_admin_headers(user_id: str = "test-org-admin-1") -> dict:
    """For OrgAdmin (opaque identity)."""
    return build_user_headers(user_id, "OrgAdmin")


def make_finance_headers(user_id: str = "test-finance-analyst-1") -> dict:
    """For FinanceAnalyst (opaque identity)."""
    return build_user_headers(user_id, "FinanceAnalyst")


def make_manager_headers(user_id: str) -> dict:
    """For LinkedAccountManager (identity equals a LinkedAccount id). Pass the
    actual LinkedAccount.id as user_id whenever the call is ownership-gated
    (e.g. ingesting usage for that account)."""
    return build_user_headers(user_id, "LinkedAccountManager")
