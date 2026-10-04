"""Pre-built role headers for every role in the PRD (PRD §2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise ownership.
TEST_USERS = {
    # opaque roles: shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "monitoring_service_headers": build_user_headers("test-monitoring-1", "MonitoringService"),
    "homeowner_headers": build_user_headers("test-homeowner-1", "Homeowner"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "installer_headers": build_user_headers("test-installer-1", "Installer"),
}


def make_installer_headers(user_id: str) -> dict:
    """For Installer (entity_backed:Installer). Pass the actual Installer.id as
    user_id whenever the call is ownership-gated (claim submission, design project,
    system registration, labor reimbursement)."""
    return build_user_headers(user_id, "Installer")