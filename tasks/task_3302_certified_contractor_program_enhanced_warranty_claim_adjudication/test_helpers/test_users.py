"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise ownership.
TEST_USERS = {
    "program_admin_headers": build_user_headers("test-admin-1", "ProgramAdmin"),
    "claimant_headers": build_user_headers("test-claimant-1", "Claimant"),
    "inspector_headers": build_user_headers("test-inspector-1", "Inspector"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "contractor_headers": build_user_headers("test-contractor-1", "Contractor"),
    "distributor_headers": build_user_headers("test-distributor-1", "Distributor"),
}


def make_contractor_headers(user_id: str) -> dict:
    """For Contractor (entity_backed:Contractor). Pass the actual Contractor.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Contractor")


def make_distributor_headers(user_id: str) -> dict:
    """For Distributor (entity_backed:Distributor). Pass the actual Distributor.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Distributor")


def make_inspector_headers(inspector_id: str) -> dict:
    """For Inspector: X-User-ID is the opaque inspector_id stored on the order."""
    return build_user_headers(inspector_id, "Inspector")
