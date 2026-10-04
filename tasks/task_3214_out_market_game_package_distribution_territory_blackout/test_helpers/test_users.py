"""Pre-built role headers for every role in the PRD.

Shared constants are safe for opaque roles and for tests that do not exercise
ownership. Subscriber / VenueManager are entity-backed by Account: for any
ownership-gated call, use make_subscriber_headers(account["id"]) /
make_venue_manager_headers(account["id"]) with the real account id.
"""
from prd_bench_local_runner.testing import build_user_headers

ANON_HEADERS = {"Content-Type": "application/json"}

TEST_USERS = {
    # Opaque roles: shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "league_ops_headers": build_user_headers("test-ops-1", "LeagueOps"),
    "support_agent_headers": build_user_headers("sa-jane", "SupportAgent"),
    "support_agent_other_headers": build_user_headers("sa-other", "SupportAgent"),
    "compliance_auditor_headers": build_user_headers("test-auditor-1", "ComplianceAuditor"),
    # Entity-backed roles: fallback only for non-ownership tests.
    "subscriber_headers": build_user_headers("test-subscriber-1", "Subscriber"),
    "venue_manager_headers": build_user_headers("test-venue-manager-1", "VenueManager"),
}


def make_subscriber_headers(account_id: str) -> dict:
    """For Subscriber (entity-backed by Account). Pass the actual Account.id
    whenever the call is ownership-gated (cancel, complaint, territory check,
    multiview, subscription purchase)."""
    return build_user_headers(account_id, "Subscriber")


def make_venue_manager_headers(account_id: str) -> dict:
    """For VenueManager (entity-backed by Account). Pass the actual Account.id
    whenever the call is ownership-gated (venue-license apply, cancel,
    territory check, multiview, subscription purchase)."""
    return build_user_headers(account_id, "VenueManager")


def make_support_agent_headers(user_id: str) -> dict:
    """For SupportAgent. The value of X-User-ID is recorded as created_by on
    granted overrides and governs who may later rescind."""
    return build_user_headers(user_id, "SupportAgent")
