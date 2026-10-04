"""Pre-built role headers for every role in the PRD.

The Agent role is entity-backed: when a call is ownership-gated (answering
or completing a call, disputing a review), the X-User-ID must equal the
acting Agent record's id, so per-agent headers MUST be built with
make_agent_headers(agent["id"]) — never the shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    "ops_manager_headers": build_user_headers("ops-1", "OpsManager"),
    "supervisor_headers": build_user_headers("sup-1", "Supervisor"),
    "quality_analyst_headers": build_user_headers("qa-1", "QualityAnalyst"),
    "knowledge_manager_headers": build_user_headers("km-1", "KnowledgeManager"),
    "security_officer_headers": build_user_headers("sec-1", "SecurityOfficer"),
    # Shared fallback for non-ownership calls only (e.g. reading articles).
    "agent_headers": build_user_headers("test-agent-1", "Agent"),
    "billing_analyst_headers": build_user_headers("billing-1", "BillingAnalyst"),
}


def make_agent_headers(agent_id: str) -> dict:
    """Headers for the entity-backed Agent role. Pass the actual Agent.id
    whenever the call is ownership-gated (answer/complete/dispute)."""
    return build_user_headers(agent_id, "Agent")


def make_ops_headers(user_id: str) -> dict:
    """OpsManager headers with a specific opaque user id (needed for the
    segregation-of-duties approve path)."""
    return build_user_headers(user_id, "OpsManager")


def make_billing_headers(user_id: str) -> dict:
    """BillingAnalyst headers with a specific opaque user id (the preparer id
    is recorded on the invoice for segregation of duties)."""
    return build_user_headers(user_id, "BillingAnalyst")


def make_supervisor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "Supervisor")
