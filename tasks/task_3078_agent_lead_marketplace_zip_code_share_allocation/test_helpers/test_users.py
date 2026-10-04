"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles (MarketplaceOps, PlatformAdmin), and
# for tests that do not exercise ownership. For the entity-backed roles (Agent
# backed by Agent, BrokerageUser backed by Brokerage) the shared constants are
# fallbacks only; ownership-gated calls must use the make_*_headers builders
# with the actual entity id.
TEST_USERS = {
    "agent_headers": build_user_headers("test-agent-1", "Agent"),
    "brokerage_user_headers": build_user_headers("test-brokerage-1", "BrokerageUser"),
    "marketplace_ops_headers": build_user_headers("test-marketplace-ops-1", "MarketplaceOps"),
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
}


def make_agent_headers(agent_id: str) -> dict:
    """For Agent (entity-backed by Agent): X-User-ID must equal the acting
    agent's id whenever the call is ownership-gated (payments, pause/resume,
    offer accept, live connections, closes, credit claims, team management)."""
    return build_user_headers(agent_id, "Agent")


def make_brokerage_user_headers(brokerage_id: str) -> dict:
    """For BrokerageUser (entity-backed by Brokerage): X-User-ID must equal the
    acting brokerage's id whenever the call is ownership-gated (listing ingest,
    dispute filing)."""
    return build_user_headers(brokerage_id, "BrokerageUser")
