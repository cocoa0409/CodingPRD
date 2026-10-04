"""Pre-built role headers for every role in the PRD.

Shared constants are safe for the eight opaque-operator roles and for tests
that do not exercise ownership. The ``Member`` role is entity-backed: any
ownership-gated call must be built with ``make_member_headers(member_id)``
using the real Member id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "network_operator_headers": build_user_headers("op-1", "NetworkOperator"),
    "sponsorship_manager_headers": build_user_headers("sm-1", "SponsorshipManager"),
    "rules_admin_headers": build_user_headers("ra-1", "RulesAdministrator"),
    "rules_admin_2_headers": build_user_headers("ra-2", "RulesAdministrator"),
    "rules_admin_3_headers": build_user_headers("ra-3", "RulesAdministrator"),
    "dispute_analyst_headers": build_user_headers("da-1", "DisputeAnalyst"),
    "pricing_analyst_headers": build_user_headers("pa-1", "PricingAnalyst"),
    "fraud_analyst_headers": build_user_headers("fa-1", "FraudAnalyst"),
    "fraud_analyst_2_headers": build_user_headers("fa-2", "FraudAnalyst"),
    "settlement_operator_headers": build_user_headers("so-1", "SettlementOperator"),
    "certification_engineer_headers": build_user_headers("ce-1", "CertificationEngineer"),
    # Entity-backed role: shared constant is a fallback for non-ownership
    # tests only; never use it for member-scoped actions.
    "member_headers": build_user_headers("test-member-1", "Member"),
}


def make_member_headers(member_id: str) -> dict:
    """For the entity-backed Member role. Pass the actual Member.id whenever
    the call is ownership-gated (disputes, appeals, evidence)."""
    return build_user_headers(member_id, "Member")


def make_rules_admin_headers(user_id: str) -> dict:
    """RulesAdministrator with a specific operator id (segregation of duties)."""
    return build_user_headers(user_id, "RulesAdministrator")


def make_fraud_analyst_headers(user_id: str) -> dict:
    """FraudAnalyst with a specific operator id (segregation of duties)."""
    return build_user_headers(user_id, "FraudAnalyst")


def make_role_headers(user_id: str, role: str) -> dict:
    """Generic builder for any role/user pair."""
    return build_user_headers(user_id, role)
