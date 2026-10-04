"""Pre-built role headers for every role in the PRD.

Two of the six roles are backed by persisted entities; their headers must
carry the acting entity's own `id` whenever the downstream call is
ownership-gated. Use the per-instance builders for those.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not
# exercise ownership.
TEST_USERS = {
    # entity_backed:Agent — shared constant is a fallback for non-ownership calls only.
    "freight_agent_headers": build_user_headers("test-freight-agent-1", "FreightAgent"),
    # entity_backed:CapacityOwner — shared constant is a fallback for non-ownership calls only.
    "capacity_owner_headers": build_user_headers("test-capacity-owner-1", "CapacityOwnerOperator"),
    # opaque operator identities
    "safety_reviewer_headers": build_user_headers("safety-reviewer-1", "SafetyReviewer"),
    "settlement_operator_headers": build_user_headers("settlement-operator-1", "SettlementOperator"),
    "network_admin_headers": build_user_headers("network-admin-1", "NetworkAdministrator"),
    "agent_manager_headers": build_user_headers("agent-manager-1", "AgentManager"),
    # A distinct settlement-clerk identity, needed for the segregation-of-duties
    # comparison where the approver must differ from the submitter.
    "settlement_operator_headers_2": build_user_headers("settlement-operator-2", "SettlementOperator"),
}


def make_freight_agent_headers(user_id: str) -> dict:
    """For FreightAgent (entity_backed:Agent). Pass the actual Agent.id as
    user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "FreightAgent")


def make_capacity_owner_headers(user_id: str) -> dict:
    """For CapacityOwnerOperator (entity_backed:CapacityOwner). Pass the actual
    CapacityOwner.id as user_id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "CapacityOwnerOperator")


def make_network_admin_headers(user_id: str = "network-admin-1") -> dict:
    """For NetworkAdministrator. The identity is opaque, but distinct identities
    are needed for the segregation-of-duties check on settlement approval."""
    return build_user_headers(user_id, "NetworkAdministrator")


def make_settlement_operator_headers(user_id: str = "settlement-operator-1") -> dict:
    """For SettlementOperator. Opaque identity; pass a distinct value when the
    segregation-of-duties check is under test."""
    return build_user_headers(user_id, "SettlementOperator")


def make_safety_reviewer_headers(user_id: str = "safety-reviewer-1") -> dict:
    """For SafetyReviewer (opaque identity)."""
    return build_user_headers(user_id, "SafetyReviewer")


def make_agent_manager_headers(user_id: str = "agent-manager-1") -> dict:
    """For AgentManager (opaque identity)."""
    return build_user_headers(user_id, "AgentManager")