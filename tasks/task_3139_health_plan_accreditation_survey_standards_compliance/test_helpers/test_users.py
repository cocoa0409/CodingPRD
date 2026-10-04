"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. PlanCoordinator and Surveyor are entity-backed: ownership-gated
# calls MUST use the per-instance builders below with the real entity id.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "accreditation_officer_headers": build_user_headers("test-officer-1", "AccreditationOfficer"),
    # entity-backed fallbacks — only for tests that never touch ownership checks
    "plan_coordinator_headers": build_user_headers("test-plan-coordinator-1", "PlanCoordinator"),
    "surveyor_headers": build_user_headers("test-surveyor-1", "Surveyor"),
    "public_viewer_headers": build_user_headers("test-public-viewer-1", "PublicViewer"),
}


def make_plan_coordinator_headers(user_id: str) -> dict:
    """For PlanCoordinator (entity-backed: HealthPlan). Pass the actual
    HealthPlan.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "PlanCoordinator")


def make_surveyor_headers(user_id: str) -> dict:
    """For Surveyor (entity-backed: Surveyor). Pass the actual Surveyor.id as
    user_id whenever the call is ownership-gated (session complete, question log)."""
    return build_user_headers(user_id, "Surveyor")


def make_platform_admin_headers(user_id: str = "test-platform-admin-1") -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_accreditation_officer_headers(user_id: str = "test-officer-1") -> dict:
    return build_user_headers(user_id, "AccreditationOfficer")


def make_public_viewer_headers(user_id: str = "test-public-viewer-1") -> dict:
    return build_user_headers(user_id, "PublicViewer")
