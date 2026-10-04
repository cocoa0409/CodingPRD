"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for the opaque operator roles, and for tests that do
# not exercise ownership. Five of the seven roles carry identifiers that "are
# opaque, untethered from the persisted graph" (PRD 2.1).
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "sales_engineer_ops_headers": build_user_headers("test-sales-engineer-ops-1", "SalesEngineerOps"),
    "setup_technician_headers": build_user_headers("test-setup-technician-1", "SetupTechnician"),
    "support_agent_headers": build_user_headers("test-support-agent-1", "SupportAgent"),
    "service_department_headers": build_user_headers("test-service-department-1", "ServiceDepartment"),
    "anonymous_headers": build_user_headers("test-anonymous-1", "Anonymous"),
    # Engineer is entity_backed: this fallback is only for tests that never
    # exercise book ownership (e.g., role-denial checks).
    "engineer_headers": build_user_headers("test-engineer-1", "Engineer"),
}


def make_engineer_headers(engineer_id: str) -> dict:
    """For Engineer (entity_backed:Engineer). Pass the actual Engineer.id
    whenever the call is ownership-gated (accept/decline own book row,
    amend/reopen own quote, place/cancel own backorder)."""
    return build_user_headers(engineer_id, "Engineer")


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_sales_engineer_ops_headers(user_id: str = "test-sales-engineer-ops-1") -> dict:
    return build_user_headers(user_id, "SalesEngineerOps")


def make_setup_technician_headers(user_id: str = "test-setup-technician-1") -> dict:
    return build_user_headers(user_id, "SetupTechnician")


def make_support_agent_headers(user_id: str = "test-support-agent-1") -> dict:
    return build_user_headers(user_id, "SupportAgent")


def make_service_department_headers(user_id: str = "test-service-department-1") -> dict:
    return build_user_headers(user_id, "ServiceDepartment")


def make_anonymous_headers(user_id: str = "test-anonymous-1") -> dict:
    return build_user_headers(user_id, "Anonymous")