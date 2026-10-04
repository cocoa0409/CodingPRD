"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not
# exercise Customer ownership gating.
TEST_USERS = {
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "sales_headers": build_user_headers("test-sales-1", "SalesAssociate"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "technician_headers": build_user_headers("test-tech-1", "DeliveryTechnician"),
    "service_headers": build_user_headers("test-service-1", "ServiceAgent"),
    "finance_headers": build_user_headers("test-finance-1", "FinanceAgent"),
    "gateway_headers": build_user_headers("test-gateway-1", "DeviceGateway"),
}


def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Customer")
