"""Pre-built role headers for every role in the PRD (§2.1).

The Customer role is entity-backed: X-User-ID must equal the acting customer
record's id whenever the call is ownership-gated. Fixtures and tests that act
on a customer's own resources MUST use make_customer_headers(customer["id"]).
Opaque roles (PlatformAdmin, StoreOps, DeliveryCoordinator, AssemblyProvider)
never have their X-User-ID compared to an entity id, so shared constants are
safe for them.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "store_ops_headers": build_user_headers("test-store-ops-1", "StoreOps"),
    "delivery_coordinator_headers": build_user_headers("test-delivery-coordinator-1", "DeliveryCoordinator"),
    "assembly_provider_headers": build_user_headers("test-assembly-provider-1", "AssemblyProvider"),
    # Fallback for non-ownership paths only (e.g. a Customer attempting a
    # PlatformAdmin-only endpoint). Never use for ownership-gated calls.
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_customer_headers(customer_id: str) -> dict:
    """Customer is entity-backed: pass the actual Customer.id whenever the
    call is ownership-gated (orders, reservations, bookings, jobs, claims,
    returns owned by that customer)."""
    return build_user_headers(customer_id, "Customer")
