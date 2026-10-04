"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# cardholder ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "issuer_operator_headers": build_user_headers("test-issuer-operator-1", "IssuerOperator"),
    "customer_service_headers": build_user_headers("test-customer-service-1", "CustomerService"),
    # Fallback only; ownership-gated calls must use make_cardholder_headers.
    "cardholder_headers": build_user_headers("test-cardholder-1", "Cardholder"),
}


def make_cardholder_headers(cardholder_id: str) -> dict:
    """Cardholder is entity-backed: X-User-ID must equal the Cardholder.id
    whenever the call is ownership-scoped."""
    return build_user_headers(cardholder_id, "Cardholder")


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_issuer_operator_headers(user_id: str = "test-issuer-operator-1") -> dict:
    return build_user_headers(user_id, "IssuerOperator")


def make_customer_service_headers(user_id: str = "test-customer-service-1") -> dict:
    return build_user_headers(user_id, "CustomerService")
