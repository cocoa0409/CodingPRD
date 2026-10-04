"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not
# exercise ownership gating on entity-backed roles.
TEST_USERS = {
    # opaque roles: shared constants are the canonical form.
    "store_admin_headers": build_user_headers("test-store-admin-1", "StoreAdmin"),
    "guest_service_headers": build_user_headers("test-guest-service-1", "GuestService"),
    "fraud_analyst_headers": build_user_headers("test-fraud-analyst-1", "FraudAnalyst"),
    "finance_admin_headers": build_user_headers("test-finance-admin-1", "FinanceAdmin"),
    # entity_backed roles: shared constants are fallbacks for non-ownership
    # tests only (e.g. 400-on-bad-payload probes).
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "contractor_headers": build_user_headers("test-contractor-1", "Contractor"),
}

# Empty header set — unauthenticated caller.
NO_AUTH_HEADERS = {"Content-Type": "application/json"}


# Per-instance builders — required for every entity_backed role.
def make_customer_headers(user_id: str) -> dict:
    """For Customer (entity_backed:CreditAccount). Pass the actual
    CreditAccount.id as user_id whenever the call is ownership-gated
    (submissions, resubmits, own-account reads)."""
    return build_user_headers(user_id, "Customer")


def make_contractor_headers(user_id: str) -> dict:
    """For Contractor (entity_backed:CreditAccount). Pass the actual
    CreditAccount.id as user_id whenever the call is ownership-gated
    (job purchases, contractor summary, submissions)."""
    return build_user_headers(user_id, "Contractor")
