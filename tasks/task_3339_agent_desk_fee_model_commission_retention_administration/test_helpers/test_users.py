"""Pre-built role headers for every role in the PRD (§2.1).

Shared constants are safe for opaque roles and for tests that do not exercise
ownership. The Agent role is entity-backed: use make_agent_headers(agent_id)
whenever the call is ownership-gated (pay own invoice, accept own assignment,
terminate self, return own advance).
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "franchisee_owner_headers": build_user_headers("test-owner-1", "FranchiseeOwner"),
    "broker_of_record_headers": build_user_headers("test-broker-1", "BrokerOfRecord"),
    "managing_broker_headers": build_user_headers("test-mgr-1", "ManagingBroker"),
    "agent_headers": build_user_headers("test-agent-1", "Agent"),
    "trust_accountant_headers": build_user_headers("test-trust-1", "TrustAccountant"),
    "compliance_auditor_headers": build_user_headers("test-compliance-1", "ComplianceAuditor"),
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
}


def make_agent_headers(agent_id: str) -> dict:
    """Agent is entity-backed: pass the actual Agent.id whenever the call is
    ownership-gated (X-User-ID must equal the agent's id, PRD §2.1)."""
    return build_user_headers(agent_id, "Agent")
