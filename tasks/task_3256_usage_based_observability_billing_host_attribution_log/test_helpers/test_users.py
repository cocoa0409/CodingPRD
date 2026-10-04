"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership. TeamLead is entity-backed by Team; the shared constant is a fallback
# only — ownership-gated calls must use make_team_lead_headers with the actual
# Team.id.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "billing_admin_headers": build_user_headers("test-billing-admin-1", "BillingAdmin"),
    "ingestion_agent_headers": build_user_headers("test-ingestion-agent-1", "IngestionAgent"),
    "team_lead_headers": build_user_headers("test-team-lead-1", "TeamLead"),
    "finance_reader_headers": build_user_headers("test-finance-reader-1", "FinanceReader"),
}


def make_team_lead_headers(team_id: str) -> dict:
    """For TeamLead (entity-backed by Team): X-User-ID must equal the acting
    Team's id whenever the call is ownership-gated (opening attribution
    disputes, team-scoped reads)."""
    return build_user_headers(team_id, "TeamLead")
