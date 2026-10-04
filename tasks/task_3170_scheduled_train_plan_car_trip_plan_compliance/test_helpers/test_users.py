"""Pre-built role headers for every role in the PRD.

All roles are opaque: X-User-ID is not tied to any persisted entity, so
shared constants are the canonical form for every role.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "network_planner_headers": build_user_headers("test-np-1", "NetworkPlanner"),
    "crew_dispatcher_headers": build_user_headers("test-cd-1", "CrewDispatcher"),
    "power_planner_headers": build_user_headers("test-pp-1", "PowerPlanner"),
    "terminal_superintendent_headers": build_user_headers("test-ts-1", "TerminalSuperintendent"),
    "service_manager_headers": build_user_headers("test-sm-1", "ServiceManager"),
    "any_headers": build_user_headers("test-any-1", "Any"),
}

# A deliberately empty header set for unauthenticated-request tests.
ANONYMOUS_HEADERS = {"Content-Type": "application/json"}
