"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for tests that don't exercise ownership.
TEST_USERS = {
    # opaque roles: shared constant is the canonical form
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "logistics_agent_headers": build_user_headers("test-logistics-agent-1", "LogisticsAgent"),
    # entity_backed roles: shared constant is a fallback for non-ownership tests only
    "account_admin_headers": build_user_headers("test-account-admin-1", "AccountAdmin"),
    "partner_manager_headers": build_user_headers("test-partner-manager-1", "PartnerManager"),
}


# Per-instance builders — required for entity_backed roles (identity threading).
def make_account_admin_headers(smart_account_id: str) -> dict:
    """For AccountAdmin (X-User-ID is the SmartAccount.id they administer)."""
    return build_user_headers(smart_account_id, "AccountAdmin")


def make_partner_manager_headers(partner_org_id: str) -> dict:
    """For PartnerManager (X-User-ID is the PartnerOrg.id)."""
    return build_user_headers(partner_org_id, "PartnerManager")
