"""Pre-built role headers for every role in the PRD (§2.1).

Opaque roles use shared constants. Entity-backed roles (ManagingPartner,
MarketPartner) MUST be built per entity via make_managing_partner_headers /
make_market_partner_headers with the actual Partner.id when the call is
ownership-gated.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # opaque roles — canonical shared form
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "hr_recruiter_headers": build_user_headers("test-recruiter-1", "HRRecruiter"),
    "corporate_controller_headers": build_user_headers(
        "test-controller-1", "CorporateController"
    ),
    "operations_auditor_headers": build_user_headers(
        "test-auditor-1", "OperationsAuditor"
    ),
    # entity_backed fallbacks — safe ONLY for tests that never exercise
    # ownership (e.g., 400-on-bad-payload, 404-on-missing-resource).
    "managing_partner_headers": build_user_headers(
        "test-managing-partner-1", "ManagingPartner"
    ),
    "market_partner_headers": build_user_headers(
        "test-market-partner-1", "MarketPartner"
    ),
}


def make_managing_partner_headers(user_id: str) -> dict:
    """ManagingPartner is entity-backed: pass the acting Partner.id as user_id
    whenever the call is ownership-gated (funding, renewals, departures,
    disputes)."""
    return build_user_headers(user_id, "ManagingPartner")


def make_market_partner_headers(user_id: str) -> dict:
    """MarketPartner is entity-backed: pass the acting Partner.id as user_id."""
    return build_user_headers(user_id, "MarketPartner")
