"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "anonymous_headers": build_user_headers("anon-registrant-1", "Anonymous"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "researcher_headers": build_user_headers("test-researcher-1", "Researcher"),
    "triager_headers": build_user_headers("test-triager-1", "Triager"),
    "program_admin_headers": build_user_headers("test-program-admin-1", "ProgramAdmin"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
}


# Per-instance builder — required for the entity_backed Researcher role.
def make_researcher_headers(user_id: str) -> dict:
    """For Researcher (entity_backed:Researcher). Pass the actual Researcher.id
    as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Researcher")
