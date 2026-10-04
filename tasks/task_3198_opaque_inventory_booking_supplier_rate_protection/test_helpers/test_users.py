"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (PlatformAdmin, CustomerService,
# FinanceOps), and for Customer-role tests that do not exercise ownership.
# For Customer (entity-backed by Customer) the shared constant is a fallback
# only; ownership-gated calls must use make_customer_headers with the actual
# customer id.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "customer_service_headers": build_user_headers("test-customer-service-1", "CustomerService"),
    "finance_ops_headers": build_user_headers("test-finance-ops-1", "FinanceOps"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity-backed by Customer): X-User-ID must equal the acting
    customer's id whenever the call is ownership-gated (bid placement,
    withdrawal, complaint intake, own-resource reads)."""
    return build_user_headers(customer_id, "Customer")
