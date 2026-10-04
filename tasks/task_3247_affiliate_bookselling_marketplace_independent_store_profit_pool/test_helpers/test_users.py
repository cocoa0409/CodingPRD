"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership. For StoreManager / Partner (entity-backed) the shared constant is
# a fallback only; ownership-gated calls must use the per-instance builders
# below with the actual entity id.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "customer_service_headers": build_user_headers("test-cs-1", "CustomerService"),
    "wholesaler_ops_headers": build_user_headers("test-wholesale-1", "WholesalerOps"),
    "finance_ops_headers": build_user_headers("test-finance-1", "FinanceOps"),
    "store_manager_headers": build_user_headers("test-store-manager-1", "StoreManager"),
    "partner_headers": build_user_headers("test-partner-1", "Partner"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_store_manager_headers(store_id: str) -> dict:
    """For StoreManager (entity-backed by AffiliateStore): X-User-ID must equal
    the acting store's id whenever the call is ownership-gated (list creation
    and list lifecycle actions)."""
    return build_user_headers(store_id, "StoreManager")


def make_partner_headers(partner_id: str) -> dict:
    """For Partner (entity-backed by AffiliatePartner): X-User-ID must equal the
    acting partner's id whenever the call is ownership-gated."""
    return build_user_headers(partner_id, "Partner")


def make_customer_headers(customer_id: str) -> dict:
    """For Customer (opaque handle): X-User-ID must equal the order's
    customer_id on any endpoint acting on an order, its returns, or its
    tickets."""
    return build_user_headers(customer_id, "Customer")
