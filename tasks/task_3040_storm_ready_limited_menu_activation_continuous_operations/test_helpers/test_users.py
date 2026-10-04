"""Pre-built role headers for every role in the PRD (§2.1).

All five roles are opaque: X-User-ID is never matched against a persisted
entity id, so the shared constants below are the canonical form for every
call. Tests that need a specific identity (e.g. segregation-of-duties
scenarios) build headers inline with build_user_headers.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "CommandCenterAdmin"),
    "unit_manager_headers": build_user_headers("test-um-1", "UnitManager"),
    "logistics_planner_headers": build_user_headers("test-lp-1", "LogisticsPlanner"),
    "field_coordinator_headers": build_user_headers("test-fc-1", "FieldCoordinator"),
    "relief_coordinator_headers": build_user_headers("test-rc-1", "ReliefCoordinator"),
}
