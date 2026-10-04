"""Pre-built role headers for every role in the PRD (§2.1).

All seven roles use an opaque X-User-ID (never tied to an entity id), so the
shared constants are the canonical form; builders exist to mint headers with a
specific X-User-ID for segregation-of-duties scenarios.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "club_admin_headers": build_user_headers("test-club-admin-1", "ClubAdmin"),
    "member_services_rep_headers": build_user_headers("test-msr-1", "MemberServicesRep"),
    "dispatcher_headers": build_user_headers("test-dispatcher-1", "Dispatcher"),
    "provider_ops_headers": build_user_headers("test-provider-ops-1", "ProviderOps"),
    "settlement_clerk_headers": build_user_headers("test-clerk-1", "SettlementClerk"),
    "federation_finance_headers": build_user_headers("test-finance-1", "FederationFinance"),
    "agent_headers": build_user_headers("test-agent-1", "Agent"),
}


def make_club_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ClubAdmin")


def make_member_services_rep_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MemberServicesRep")


def make_dispatcher_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Dispatcher")


def make_provider_ops_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ProviderOps")


def make_settlement_clerk_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SettlementClerk")


def make_federation_finance_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FederationFinance")


def make_agent_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Agent")
