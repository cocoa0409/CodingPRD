"""Pre-built role headers for every role in the PRD (§2.1).

Shared constants are safe for opaque roles and for tests that do not exercise
ownership. For the Policyholder role (identity entity_backed:Policyholder),
fixtures MUST call make_policyholder_headers(<policyholder id>) so ownership
checks pass.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
    "underwriting_admin_headers": build_user_headers("uw-admin-1", "UnderwritingAdmin"),
    "adjuster_1_headers": build_user_headers("adj-1", "ClaimsAdjuster"),
    "adjuster_2_headers": build_user_headers("adj-2", "ClaimsAdjuster"),
    "finance_ops_headers": build_user_headers("fin-ops-1", "FinanceOps"),
    "platform_admin_headers": build_user_headers("platform-1", "PlatformAdmin"),
    # entity_backed role: fallback only for non-ownership calls.
    "policyholder_headers": build_user_headers("test-policyholder-1", "Policyholder"),
}


def make_policyholder_headers(user_id: str) -> dict:
    """For the Policyholder role (entity_backed:Policyholder). Pass the actual
    Policyholder.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Policyholder")


def make_adjuster_headers(user_id: str) -> dict:
    """For a ClaimsAdjuster operator id (opaque, but recorded on denials so
    appeal segregation-of-duties can compare reviewer vs denier)."""
    return build_user_headers(user_id, "ClaimsAdjuster")
