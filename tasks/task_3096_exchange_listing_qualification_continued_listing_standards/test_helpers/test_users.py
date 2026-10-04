"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not exercise
# entity-backed ownership (IssuerOfficer ownership is only enforced when the
# X-User-ID must equal the {issuerId} path segment).
TEST_USERS = {
    # entity_backed:Issuer — shared constant is a fallback for non-ownership tests only.
    "issuer_officer_headers": build_user_headers("test-issuer-officer-1", "IssuerOfficer"),
    # opaque roles — shared constants are canonical.
    "listing_analyst_headers": build_user_headers("test-analyst-1", "ListingAnalyst"),
    "listing_analyst_2_headers": build_user_headers("test-analyst-2", "ListingAnalyst"),
    "hearings_officer_headers": build_user_headers("test-hearings-1", "HearingsOfficer"),
    "listings_council_headers": build_user_headers("test-council-1", "ListingsCouncil"),
    "finance_officer_headers": build_user_headers("test-finance-1", "FinanceOfficer"),
}


def make_issuer_officer_headers(issuer_id: str) -> dict:
    """For IssuerOfficer (entity_backed:Issuer). Pass the actual Issuer.id as
    issuer_id whenever the call is ownership-gated (any /issuers/{issuerId}/... path)."""
    return build_user_headers(issuer_id, "IssuerOfficer")
