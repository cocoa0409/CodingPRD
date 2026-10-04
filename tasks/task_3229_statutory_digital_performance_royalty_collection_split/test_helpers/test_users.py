"""Pre-built role headers for every role in the PRD (§2.1).

The Licensee role is entity-backed: ownership checks compare the resource's
licensee foreign key to X-User-ID, so any ownership-gated call MUST use
make_licensee_headers(licensee["id"]) with the real Licensee id. The shared
constant below is a fallback only for tests that do not exercise ownership.

All other roles are opaque operator identifiers per PRD §2.1.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # entity_backed role: fallback for non-ownership tests only.
    "licensee_headers": build_user_headers("test-licensee-1", "Licensee"),
    # opaque roles: shared constants are the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "Admin"),
    "royalty_ops_headers": build_user_headers("test-royalty-ops-1", "RoyaltyOps"),
    "payee_admin_headers": build_user_headers("test-payee-admin-1", "PayeeAdmin"),
    "statutory_board_headers": build_user_headers("test-board-1", "StatutoryBoard"),
    "royalty_auditor_headers": build_user_headers("test-auditor-1", "RoyaltyAuditor"),
    "matching_agent_headers": build_user_headers("test-matcher-1", "MatchingAgent"),
}


def make_licensee_headers(user_id: str) -> dict:
    """For the Licensee role. Pass the actual Licensee.id as user_id whenever
    the call is ownership-gated (report creation, play lines, submit, amend)."""
    return build_user_headers(user_id, "Licensee")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "Admin")


def make_royalty_ops_headers(user_id: str = "test-royalty-ops-1") -> dict:
    return build_user_headers(user_id, "RoyaltyOps")


def make_payee_admin_headers(user_id: str = "test-payee-admin-1") -> dict:
    return build_user_headers(user_id, "PayeeAdmin")


def make_statutory_board_headers(user_id: str = "test-board-1") -> dict:
    return build_user_headers(user_id, "StatutoryBoard")


def make_royalty_auditor_headers(user_id: str = "test-auditor-1") -> dict:
    return build_user_headers(user_id, "RoyaltyAuditor")


def make_matching_agent_headers(user_id: str = "test-matcher-1") -> dict:
    return build_user_headers(user_id, "MatchingAgent")
