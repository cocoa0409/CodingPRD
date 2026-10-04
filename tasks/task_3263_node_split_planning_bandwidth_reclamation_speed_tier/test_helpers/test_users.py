"""Pre-built role headers for every role in the PRD (§2.1).

All seven operational roles are opaque (PRD §2.1: `X-User-ID` is an opaque
operator identifier not tied to any persisted entity), so the shared
constants are the canonical form for every role.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "network_planner_headers": build_user_headers("test-network-planner-1", "NetworkPlanner"),
    "capacity_engineer_headers": build_user_headers("test-capacity-engineer-1", "CapacityEngineer"),
    "field_ops_coordinator_headers": build_user_headers("test-field-ops-coordinator-1", "FieldOpsCoordinator"),
    "franchise_admin_headers": build_user_headers("test-franchise-admin-1", "FranchiseAdmin"),
    "provisioning_agent_headers": build_user_headers("test-provisioning-agent-1", "ProvisioningAgent"),
    "customer_care_headers": build_user_headers("test-customer-care-1", "CustomerCare"),
}
