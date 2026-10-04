"""Pre-built role headers for every role in the PRD (§2.1).

OrgOwner is entity-backed: when a call is ownership-gated, the X-User-ID must be
the acting org's actual id — use make_org_owner_headers(org_id). The shared
constant is a fallback only for tests that never exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "finance_headers": build_user_headers("test-finance-1", "FinanceOps"),
    "auditor_headers": build_user_headers("test-auditor-1", "Auditor"),
    "reviewer_headers": build_user_headers("test-reviewer-1", "ReviewBoard"),
    # Entity-backed role: fallback for non-ownership tests ONLY.
    "org_owner_headers": build_user_headers("test-org-owner-1", "OrgOwner"),
}


def make_org_owner_headers(org_id: str) -> dict:
    """For OrgOwner (entity-backed: DeveloperOrg). Pass the actual org's id as
    org_id whenever the call is ownership-gated (projects, reports, listings,
    subscriptions, agreements, migration, purchases)."""
    return build_user_headers(org_id, "OrgOwner")
