"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. EnterpriseAdmin / OrgAdmin / RunnerAgent / Any are opaque
# identities (X-User-ID is not compared against any entity id), so the shared
# constant is the canonical form. The UserAccount constant is a fallback only
# for tests that do not exercise ownership.
TEST_USERS = {
    "enterprise_admin_headers": build_user_headers("test-ea-1", "EnterpriseAdmin"),
    "org_admin_headers": build_user_headers("test-oa-1", "OrgAdmin"),
    "runner_agent_headers": build_user_headers("test-ra-1", "RunnerAgent"),
    "any_headers": build_user_headers("test-any-1", "EnterpriseAdmin"),
    "user_account_headers": build_user_headers("test-user-1", "UserAccount"),
}


def make_user_headers(user_id: str) -> dict:
    """Headers for the UserAccount role (entity-backed identity).

    Pass the actual UserAccount.id as user_id whenever the call is
    ownership-gated (collaborator accept, PAT create/revoke).
    """
    return build_user_headers(user_id, "UserAccount")
