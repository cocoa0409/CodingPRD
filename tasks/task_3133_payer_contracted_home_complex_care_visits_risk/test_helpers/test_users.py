"""Pre-built role headers for every role in the PRD (section 2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise
# clinician ownership. The Clinician role is identity-bound: its X-User-ID must
# equal a real Clinician.id, so ownership-gated calls MUST use
# make_clinician_headers() with the actual clinician id.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "contract_admin_headers": build_user_headers("test-contract-admin-1", "ContractAdministrator"),
    "engagement_specialist_headers": build_user_headers("test-engagement-specialist-1", "EngagementSpecialist"),
    "care_coordinator_headers": build_user_headers("test-care-coordinator-1", "CareCoordinator"),
    "performance_analyst_headers": build_user_headers("test-performance-analyst-1", "PerformanceAnalyst"),
}


def make_clinician_headers(clinician_id: str) -> dict:
    """For the identity-bound Clinician role. Pass the actual Clinician.id
    whenever the call is ownership-gated (visits and urgent episodes)."""
    return build_user_headers(clinician_id, "Clinician")


def clinician_headers_for(clinician_id: str) -> dict:
    return make_clinician_headers(clinician_id)
