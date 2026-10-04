"""Pre-built role headers for every role in the PRD.

Shared constants are safe for opaque roles and for tests that do not exercise
ownership. Entity-backed roles (Publisher, Songwriter, Licensee) MUST use the
per-instance builders with the actual entity id whenever the call is
ownership-gated (PRD §2.1: for those roles X-User-ID is the entity's id).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "pro_registrar_headers": build_user_headers("test-registrar-1", "ProRegistrar"),
    "pro_licensing_admin_headers": build_user_headers("test-licensing-admin-1", "ProLicensingAdmin"),
    "rate_court_officer_headers": build_user_headers("test-court-officer-1", "RateCourtOfficer"),
    "royalty_distributor_headers": build_user_headers("test-distributor-1", "RoyaltyDistributor"),
    "finance_officer_headers": build_user_headers("test-finance-1", "FinanceOfficer"),
    "finance_officer_2_headers": build_user_headers("test-finance-2", "FinanceOfficer"),
    "pro_system_admin_headers": build_user_headers("test-sysadmin-1", "ProSystemAdmin"),
    # Fallbacks for entity-backed roles — only for non-ownership contexts.
    "publisher_headers": build_user_headers("test-publisher-1", "Publisher"),
    "songwriter_headers": build_user_headers("test-songwriter-1", "Songwriter"),
    "licensee_headers": build_user_headers("test-licensee-1", "Licensee"),
}


def make_publisher_headers(affiliate_id: str) -> dict:
    """Publisher is entity-backed by Affiliate: pass the actual Affiliate.id."""
    return build_user_headers(affiliate_id, "Publisher")


def make_songwriter_headers(affiliate_id: str) -> dict:
    """Songwriter is entity-backed by Affiliate: pass the actual Affiliate.id."""
    return build_user_headers(affiliate_id, "Songwriter")


def make_licensee_headers(licensee_id: str) -> dict:
    """Licensee is entity-backed by Licensee: pass the actual Licensee.id."""
    return build_user_headers(licensee_id, "Licensee")


def make_finance_officer_headers(user_id: str) -> dict:
    """Opaque FinanceOfficer identity with a specific user id (segregation-of-duties tests)."""
    return build_user_headers(user_id, "FinanceOfficer")
