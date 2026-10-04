"""Pre-built role headers for every role in the API.

``Vendor`` and ``Customer`` are entity-backed: their ``X-User-ID`` is the identifier
of an actual entity, and ownership checks compare that identifier to the resource's
foreign key. The shared constants below are therefore only safe for requests that do
not exercise ownership; every ownership-gated call must use the per-instance builder
with the real entity's ``id``.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque operator roles — the shared constant is the canonical form.
    "merchandiser_headers": build_user_headers("test-merch-1", "Merchandiser"),
    "inventory_planner_headers": build_user_headers("test-planner-1", "InventoryPlanner"),
    "cross_dock_headers": build_user_headers("test-dock-1", "CrossDockOperator"),
    "customer_service_headers": build_user_headers("test-cs-1", "CustomerService"),
    "any_headers": build_user_headers("test-any-1", "Any"),
    # entity_backed roles — the shared constants are fallbacks for non-ownership
    # requests only; prefer the make_* builders below.
    "vendor_headers": build_user_headers("test-vendor-1", "Vendor"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}

# No user context at all — used to exercise the identity check.
NO_USER_HEADERS: dict = {"Content-Type": "application/json"}


def make_vendor_headers(vendor_id: str) -> dict:
    """Headers for a Vendor acting as itself. Pass the real Vendor.id whenever the
    call is ownership-gated (shipment reports, line confirmations)."""
    return build_user_headers(vendor_id, "Vendor")


def make_customer_headers(customer_id: str) -> dict:
    """Headers for a Customer acting as itself. Pass the real Customer.id whenever
    the call addresses an order or the customer record."""
    return build_user_headers(customer_id, "Customer")


def make_role_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary identity/role pair."""
    return build_user_headers(user_id, role)