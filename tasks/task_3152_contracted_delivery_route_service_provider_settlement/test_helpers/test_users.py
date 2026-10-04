"""Pre-built role headers for every role in the PRD (§2.1).

`ServiceProvider` is the one entity-backed role: its `X-User-ID` must be the
`id` of an acting `ServiceProvider` row. The per-instance builder
`make_service_provider_headers(provider_id)` is mandatory whenever a call is
ownership-gated (filing a dispute, moving a title, submitting an agreement).
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and tests that do not exercise ownership.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "account_manager_headers": build_user_headers("test-account-manager-1", "AccountManager"),
    "settlement_analyst_headers": build_user_headers("test-settlement-analyst-1", "SettlementAnalyst"),
    "compliance_officer_headers": build_user_headers("test-compliance-officer-1", "ComplianceOfficer"),
    # entity_backed role: the shared constant is a non-ownership fallback only.
    "service_provider_headers": build_user_headers(
        "00000000-0000-4000-8000-000000000001", "ServiceProvider"
    ),
    # Anonymous carries well-formed headers with a role outside every endpoint's list.
    "anonymous_headers": build_user_headers("anon-1", "Anonymous"),
}


def make_service_provider_headers(provider_id: str) -> dict:
    """For ServiceProvider (entity_backed:ServiceProvider). Pass the actual
    ServiceProvider.id as the user id whenever the call is ownership-gated."""
    return build_user_headers(provider_id, "ServiceProvider")