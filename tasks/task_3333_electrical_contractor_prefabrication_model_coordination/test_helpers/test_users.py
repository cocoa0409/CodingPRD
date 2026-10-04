"""Pre-built role headers for every role in the PRD (PRD §2.1).

All eight roles in this service are opaque operators, so the shared constants
are the canonical form for every test.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "project_manager_headers": build_user_headers("test-pm-1", "ProjectManager"),
    "model_coordinator_headers": build_user_headers("test-mc-1", "ModelCoordinator"),
    "shop_foreman_headers": build_user_headers("test-sf-1", "ShopForeman"),
    "logistics_headers": build_user_headers("test-log-1", "LogisticsCoordinator"),
    "procurement_headers": build_user_headers("test-proc-1", "ProcurementLead"),
    "general_foreman_headers": build_user_headers("test-gf-1", "GeneralForeman"),
    "install_foreman_headers": build_user_headers("test-if-1", "InstallForeman"),
}