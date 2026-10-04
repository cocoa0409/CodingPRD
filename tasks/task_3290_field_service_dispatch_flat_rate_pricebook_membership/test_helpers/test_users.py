"""Pre-built role headers for every role named in the PRD (§2.1).

`Dispatcher` and `Technician` are both backed by a persisted `Technician` row,
so their per-instance builders are mandatory: an ownership-gated call must carry
the acting technician's real `id`, not a fixed opaque string.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque roles and for calls whose success does
# not depend on the caller owning the subject resource.
TEST_USERS = {
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "technician_headers": build_user_headers("test-technician-1", "Technician"),
    "manager_headers": build_user_headers("test-manager-1", "Manager"),
    "customer_service_headers": build_user_headers("test-cs-1", "CustomerService"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}

MANAGER_USER_ID = "mgr-401"


def make_dispatcher_headers(technician_id: str) -> dict:
    """Dispatcher headers whose X-User-ID is a real Technician.id."""
    return build_user_headers(technician_id, "Dispatcher")


def make_technician_headers(technician_id: str) -> dict:
    """Technician headers whose X-User-ID is a real Technician.id."""
    return build_user_headers(technician_id, "Technician")