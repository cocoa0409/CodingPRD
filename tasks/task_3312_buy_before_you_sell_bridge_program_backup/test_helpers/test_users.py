"""Pre-built role headers for every role in the PRD (section 2.1).

Coordinator, Underwriter and ProgramAdmin are operational roles: their
X-User-ID is an opaque operator identifier never compared to an entity id, so
the shared constants are the canonical form for them.

Homeowner and Agent are entity-backed roles: when X-User-Role is Homeowner the
X-User-ID is the id of an acting Homeowner, and likewise for Agent. Ownership-
gated calls MUST use the per-instance builders below with the real entity id.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants: canonical for the opaque operational roles, and safe only
# for calls that do not exercise ownership.
TEST_USERS = {
    "coordinator_headers": build_user_headers("test-coordinator-1", "Coordinator"),
    "underwriter_headers": build_user_headers("test-underwriter-1", "Underwriter"),
    "program_admin_headers": build_user_headers("test-program-admin-1", "ProgramAdmin"),
    # entity-backed shared constants: fallback for non-ownership tests only.
    "homeowner_headers": build_user_headers("test-homeowner-1", "Homeowner"),
    "agent_headers": build_user_headers("test-agent-1", "Agent"),
}


def make_homeowner_headers(user_id: str) -> dict:
    """Headers for a Homeowner (entity_backed:Homeowner).

    Pass the actual Homeowner.id as user_id whenever the call is
    ownership-gated, so the resource's homeowner_id matches X-User-ID.
    """
    return build_user_headers(user_id, "Homeowner")


def make_agent_headers(user_id: str) -> dict:
    """Headers for an Agent (entity_backed:Agent).

    Pass the actual Agent.id as user_id whenever the call is ownership-gated.
    """
    return build_user_headers(user_id, "Agent")