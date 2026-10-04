"""Pre-built role headers for every role in the PRD.

PlatformAdmin, ShiftManager and KitchenStaff are opaque operator identities:
their X-User-ID is not compared to any entity's id. Carhop and Customer are
entity-backed: for any ownership-gated call, build headers with the actual
entity id via make_carhop_headers / make_customer_headers.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for non-ownership tests.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "shift_manager_headers": build_user_headers("test-shift-manager-1", "ShiftManager"),
    "kitchen_staff_headers": build_user_headers("test-kitchen-staff-1", "KitchenStaff"),
    # Entity-backed roles: fallback for tests that do not exercise ownership.
    "carhop_headers": build_user_headers("test-carhop-1", "Carhop"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
}


def make_carhop_headers(carhop_id: str) -> dict:
    """Headers for the Carhop role. Pass the actual Carhop.id whenever the
    call is ownership-gated (departing or delivering on an assigned run)."""
    return build_user_headers(carhop_id, "Carhop")


def make_customer_headers(customer_id: str) -> dict:
    """Headers for the Customer role. Pass the actual Customer.id whenever the
    call is ownership-gated (app-checkin, own-order access)."""
    return build_user_headers(customer_id, "Customer")
