"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. Dealer and Contractor are entity-backed: their per-instance
# builders below MUST be used for ownership-gated calls.
TEST_USERS = {
    "ops_manager_headers": build_user_headers("test-ops-1", "OpsManager"),
    "quality_engineer_headers": build_user_headers("test-qe-1", "QualityEngineer"),
    "process_engineer_headers": build_user_headers("test-pe-1", "ProcessEngineer"),
    "product_manager_headers": build_user_headers("test-pm-1", "ProductManager"),
    "channel_manager_headers": build_user_headers("test-cm-1", "ChannelManager"),
    "dealer_sales_rep_headers": build_user_headers("test-dsr-1", "DealerSalesRep"),
    "program_admin_headers": build_user_headers("test-pa-1", "ProgramAdmin"),
    "claims_adjuster_headers": build_user_headers("test-ca-1", "ClaimsAdjuster"),
    # entity_backed roles: shared constant is a fallback for non-ownership
    # tests only (e.g. 400/404 probes that never reach an ownership check).
    "dealer_headers": build_user_headers("test-dealer-1", "Dealer"),
    "contractor_headers": build_user_headers("test-contractor-1", "Contractor"),
}


def make_dealer_headers(dealer_id: str) -> dict:
    """For Dealer (entity_backed:Dealer). Pass the actual Dealer.id as
    dealer_id whenever the call is ownership-gated (deliver, lead submit)."""
    return build_user_headers(dealer_id, "Dealer")


def make_contractor_headers(contractor_id: str) -> dict:
    """For Contractor (entity_backed:Contractor). Pass the actual
    Contractor.id whenever the call is ownership-gated (registration actions,
    lead decline)."""
    return build_user_headers(contractor_id, "Contractor")
