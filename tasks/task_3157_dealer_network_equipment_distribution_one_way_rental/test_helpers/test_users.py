"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# ownership checks. Entity-backed roles (DealerAgent, Customer) MUST use the
# per-instance builders below whenever a call is ownership-gated.
TEST_USERS = {
    "admin": build_user_headers("test-admin-1", "NetworkAdmin"),
    "pricing": build_user_headers("test-pricing-1", "PricingManager"),
    "finance": build_user_headers("test-finance-1", "FinanceReviewer"),
    "driver_1": build_user_headers("driver-1", "RepositionDriver"),
    "driver_2": build_user_headers("driver-2", "RepositionDriver"),
    # Fallbacks for entity_backed roles — non-ownership tests only.
    "dealer_agent": build_user_headers("test-dealer-agent-1", "DealerAgent"),
    "customer": build_user_headers("test-customer-1", "Customer"),
}


def make_dealer_agent_headers(dealer_id: str) -> dict:
    """DealerAgent identity is entity-backed: X-User-ID must be the Dealer.id."""
    return build_user_headers(dealer_id, "DealerAgent")


def make_customer_headers(customer_id: str) -> dict:
    """Customer identity is entity-backed: X-User-ID must be the Customer.id."""
    return build_user_headers(customer_id, "Customer")


def make_driver_headers(driver_id: str) -> dict:
    """RepositionDriver identity is an opaque operator identifier."""
    return build_user_headers(driver_id, "RepositionDriver")


def make_finance_headers(user_id: str) -> dict:
    """FinanceReviewer identity is opaque; distinct ids matter for segregation of duties."""
    return build_user_headers(user_id, "FinanceReviewer")
