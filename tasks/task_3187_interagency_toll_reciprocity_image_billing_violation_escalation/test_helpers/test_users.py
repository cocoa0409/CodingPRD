"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that do not
# exercise AccountHolder ownership gating.
TEST_USERS = {
    "settlement_officer_headers": build_user_headers("test-settlement-officer-1", "SettlementOfficer"),
    "agency_ops_headers": build_user_headers("test-agency-ops-1", "AgencyOperations"),
    "violations_officer_headers": build_user_headers("test-violations-officer-1", "ViolationsOfficer"),
    "plate_lookup_agent_headers": build_user_headers("test-plate-lookup-agent-1", "PlateLookupAgent"),
    # AccountHolder is entity_backed on Account: this shared constant is ONLY a
    # fallback for non-ownership tests (e.g. 400/404 checks). Ownership-gated
    # calls MUST use make_account_holder_headers(account["id"]).
    "account_holder_headers": build_user_headers("test-account-holder-1", "AccountHolder"),
}


def make_account_holder_headers(user_id: str) -> dict:
    """For AccountHolder (entity_backed: Account). Pass the actual Account.id
    as user_id whenever the call is ownership-gated (close, transponder
    lifecycle, dispute file/withdraw, violation pay, own-account replenish)."""
    return build_user_headers(user_id, "AccountHolder")
