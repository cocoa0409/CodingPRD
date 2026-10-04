"""Pre-built role headers for every role in the PRD (§2.1).

All six roles use opaque operator identifiers: "X-User-ID is an opaque operator
identifier not tied to any persisted entity; the server may record it but never
compares it against any resource's id." Shared constants are therefore the
canonical form for every role — no per-instance builders are needed.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "area_director_headers": build_user_headers("test-area-director-1", "AreaDirector"),
    "partnership_manager_headers": build_user_headers("test-partnership-manager-1", "PartnershipManager"),
    "program_coordinator_headers": build_user_headers("test-program-coordinator-1", "ProgramCoordinator"),
    "logistics_coordinator_headers": build_user_headers("test-logistics-coordinator-1", "LogisticsCoordinator"),
    "funder_headers": build_user_headers("test-funder-1", "Funder"),
}
