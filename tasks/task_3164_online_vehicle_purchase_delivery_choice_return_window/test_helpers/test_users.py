"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for non-ownership tests.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "customer_advocate_headers": build_user_headers("test-customer-advocate-1", "CustomerAdvocate"),
    "recon_operator_headers": build_user_headers("test-recon-operator-1", "ReconOperator"),
    "registration_clerk_headers": build_user_headers("test-registration-clerk-1", "RegistrationClerk"),
    "warranty_admin_headers": build_user_headers("test-warranty-admin-1", "WarrantyAdmin"),
}


def make_customer_headers(customer_id: str) -> dict:
    """For Customer (entity_backed:Customer). Pass the actual Customer.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(customer_id, "Customer")
