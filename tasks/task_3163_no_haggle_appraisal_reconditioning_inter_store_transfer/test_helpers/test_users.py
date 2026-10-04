"""Pre-built role headers for every role in the PRD (Section 2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (PlatformAdmin, AuctionManager) and
# for tests that do not exercise entity-backed identity resolution. For
# entity-backed roles (all store/finance/sales/appraiser/inspector roles and
# Customer), prefer the make_*_headers builders with the real entity id.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "auction_manager_headers": build_user_headers("test-auction-1", "AuctionManager"),
    # Fallbacks for entity-backed roles — only for tests whose outcome does
    # not depend on identity resolution (e.g. header-presence checks).
    "store_manager_headers": build_user_headers("test-mgr-1", "StoreManager"),
    "appraiser_headers": build_user_headers("test-appraiser-1", "Appraiser"),
    "inspector_headers": build_user_headers("test-inspector-1",
                                            "ReconditioningInspector"),
    "sales_associate_headers": build_user_headers("test-sales-1",
                                                  "SalesAssociate"),
    "finance_manager_headers": build_user_headers("test-finance-1",
                                                  "FinanceManager"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_store_manager_headers(associate_id: str) -> dict:
    """StoreManager is entity_backed by Associate (role_kind MANAGER)."""
    return build_user_headers(associate_id, "StoreManager")


def make_appraiser_headers(associate_id: str) -> dict:
    """Appraiser is entity_backed by Associate (role_kind APPRAISER)."""
    return build_user_headers(associate_id, "Appraiser")


def make_inspector_headers(associate_id: str) -> dict:
    """ReconditioningInspector is entity_backed by Associate (role_kind INSPECTOR)."""
    return build_user_headers(associate_id, "ReconditioningInspector")


def make_sales_associate_headers(associate_id: str) -> dict:
    """SalesAssociate is entity_backed by Associate (role_kind SALES)."""
    return build_user_headers(associate_id, "SalesAssociate")


def make_finance_manager_headers(associate_id: str) -> dict:
    """FinanceManager is entity_backed by Associate (role_kind FINANCE)."""
    return build_user_headers(associate_id, "FinanceManager")


def make_customer_headers(customer_id: str) -> dict:
    """Customer is entity_backed by CustomerAccount."""
    return build_user_headers(customer_id, "Customer")


def anonymous_headers() -> dict:
    """Headers with neither X-User-ID nor X-User-Role (malformed context)."""
    return {"Content-Type": "application/json"}
