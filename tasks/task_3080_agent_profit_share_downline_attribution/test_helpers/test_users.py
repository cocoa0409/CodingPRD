"""Pre-built role headers for every role in the PRD.

PlatformAdmin and RegionalDirector are opaque roles (their X-User-ID is not
compared to any entity). MarketCenterAdmin, ALCChair, and Agent are
entity-backed: their X-User-ID must be the id of the acting Agent row, so
per-instance builders are mandatory whenever a call is ownership-gated or
tied to a specific agent identity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership or agent-identity gating.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    "regional_director_headers": build_user_headers("regional-director-1", "RegionalDirector"),
    # Fallbacks for entity-backed roles; use ONLY in non-ownership contexts.
    "market_center_admin_headers": build_user_headers("test-mca-1", "MarketCenterAdmin"),
    "alc_chair_headers": build_user_headers("test-alc-1", "ALCChair"),
    "agent_headers": build_user_headers("test-agent-1", "Agent"),
}


def make_market_center_admin_headers(agent_id: str) -> dict:
    """MarketCenterAdmin is entity-backed: pass the acting agent's id."""
    return build_user_headers(agent_id, "MarketCenterAdmin")


def make_alc_chair_headers(agent_id: str) -> dict:
    """ALCChair is entity-backed: pass the chair agent's id."""
    return build_user_headers(agent_id, "ALCChair")


def make_agent_headers(agent_id: str) -> dict:
    """Agent is entity-backed: pass the acting agent's id."""
    return build_user_headers(agent_id, "Agent")
