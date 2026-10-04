"""Pre-built role headers for every role in the PRD (§2.1).

FranchiseeAdmin is entity-backed: X-User-ID must equal the acting Brokerage's id
whenever a call is ownership-gated. Use make_franchisee_admin_headers(brokerage_id)
for those calls; the shared constant is only safe for non-ownership tests.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles: shared constants are canonical.
    "franchisor_ops_headers": build_user_headers("test-franchisor-ops-1", "FranchisorOps"),
    "brand_auditor_headers": build_user_headers("test-brand-auditor-1", "BrandAuditor"),
    # Entity-backed role: fallback for tests that do not exercise ownership.
    "franchisee_admin_headers": build_user_headers("test-franchisee-admin-1", "FranchiseeAdmin"),
}


def make_franchisee_admin_headers(brokerage_id: str) -> dict:
    """FranchiseeAdmin is entity-backed by Brokerage (PRD §2.1); pass the actual
    brokerage id whenever the call is ownership-gated."""
    return build_user_headers(brokerage_id, "FranchiseeAdmin")
