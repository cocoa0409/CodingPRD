"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "officer_headers": build_user_headers("test-officer-1", "AccreditationOfficer"),
    "pt_coordinator_headers": build_user_headers("test-ptcoord-1", "PTCoordinator"),
    # entity_backed roles: fallback only for non-ownership tests.
    "director_headers": build_user_headers("test-director-1", "LaboratoryDirector"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
}


def make_director_headers(laboratory_id: str) -> dict:
    """For LaboratoryDirector (entity_backed:Laboratory). Pass the actual
    Laboratory.id whenever the call is ownership-gated."""
    return build_user_headers(laboratory_id, "LaboratoryDirector")


def make_inspector_headers(inspector_id: str) -> dict:
    """For Inspector (entity_backed:InspectorProfile). Pass the actual
    InspectorProfile.id whenever the call is ownership-gated."""
    return build_user_headers(inspector_id, "Inspector")
