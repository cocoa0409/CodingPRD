"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque roles: shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "brand_owner_admin_headers": build_user_headers("test-brand-owner-admin-1", "BrandOwnerAdmin"),
    "field_technician_headers": build_user_headers("test-field-technician-1", "FieldTechnician"),
    # entity_backed roles: shared constant is a fallback for non-ownership tests only.
    "bottler_ops_headers": build_user_headers("test-bottler-ops-1", "BottlerOps"),
    "customer_manager_headers": build_user_headers("test-customer-manager-1", "CustomerManager"),
}


# Per-instance builders — required for every entity_backed role.
def make_bottler_ops_headers(agreement_id: str) -> dict:
    """For BottlerOps (entity_backed:BottlerAgreement). Pass the actual
    BottlerAgreement.id as agreement_id whenever the call is ownership-gated."""
    return build_user_headers(agreement_id, "BottlerOps")


def make_customer_manager_headers(customer_id: str) -> dict:
    """For CustomerManager (entity_backed:Customer). Pass the actual
    Customer.id as customer_id whenever the call is ownership-gated."""
    return build_user_headers(customer_id, "CustomerManager")
