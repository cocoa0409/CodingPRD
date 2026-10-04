"""Pre-built role headers for every role the platform recognises.

The three operator roles carry opaque identifiers, so a shared constant is the
canonical form for them. The two agent roles are entity-backed: their `X-User-ID`
must equal a real `Agent.id`, so a per-instance builder is provided and callers
that exercise ownership MUST thread the live agent id into it.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    # opaque roles — shared constants are the canonical form
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "operations_coordinator_headers": build_user_headers("test-ops-coordinator-1", "OperationsCoordinator"),
    "transaction_coordinator_headers": build_user_headers("test-txn-coordinator-1", "TransactionCoordinator"),
    # entity-backed roles — shared constants are a fallback for non-ownership tests only
    "listing_agent_headers": build_user_headers("test-listing-agent-1", "ListingAgent"),
    "associate_agent_headers": build_user_headers("test-associate-agent-1", "AssociateAgent"),
}

# Convenience aliases used widely by the test suite.
PLATFORM_ADMIN = TEST_USERS["platform_admin_headers"]
OPERATIONS_COORDINATOR = TEST_USERS["operations_coordinator_headers"]
TRANSACTION_COORDINATOR = TEST_USERS["transaction_coordinator_headers"]


def make_listing_agent_headers(agent_id: str) -> dict:
    """For ListingAgent (entity_backed:Agent). Pass the acting Agent.id whenever
    the call is ownership-gated (listing operations against a client)."""
    return build_user_headers(agent_id, "ListingAgent")


def make_associate_agent_headers(agent_id: str) -> dict:
    """For AssociateAgent (entity_backed:Agent). Pass the acting Agent.id for
    tour-staffing operations."""
    return build_user_headers(agent_id, "AssociateAgent")


def anonymous_headers() -> dict:
    """Headers carrying no role — used for the unauthenticated check."""
    return {"X-User-ID": "anonymous-caller"}