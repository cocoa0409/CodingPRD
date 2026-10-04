"""Pre-built role headers for every role in the PRD (§2.1, §4).

Customer is entity_backed: X-User-ID must equal the acting Customer.id for
ownership-gated calls (PRD §2.1). Use make_customer_headers(customer["id"])
whenever the call touches that customer's own resources. The seven
operator-side roles carry opaque user ids.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for Customer-role calls that do
# not exercise ownership (e.g., 400-on-bad-payload probes).
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "mission_ops_headers": build_user_headers("test-mops-1", "MissionOps"),
    "contract_manager_headers": build_user_headers("test-cm-1", "ContractManager"),
    "customer_headers": build_user_headers("test-customer-1", "Customer"),
    "engineer_headers": build_user_headers("eng-1", "IntegrationEngineer"),
    "safety_headers": build_user_headers("so-1", "SafetyOfficer"),
    "range_officer_headers": build_user_headers("test-ro-1", "RangeOfficer"),
    "regulator_headers": build_user_headers("test-reg-1", "Regulator"),
}


def make_customer_headers(user_id: str) -> dict:
    """Customer is entity_backed (PRD §2.1): pass the real Customer.id whenever
    the call is ownership-gated (sign, rebook, own reads, own license filings)."""
    return build_user_headers(user_id, "Customer")


def make_engineer_headers(user_id: str) -> dict:
    """IntegrationEngineer with a specific opaque user id (SoD tests)."""
    return build_user_headers(user_id, "IntegrationEngineer")


def make_safety_headers(user_id: str) -> dict:
    """SafetyOfficer with a specific opaque user id (SoD tests)."""
    return build_user_headers(user_id, "SafetyOfficer")
