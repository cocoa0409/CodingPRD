"""Pre-built role headers for every role in the PRD.

Account is an entity-backed role: X-User-ID must equal the acting Account's id,
so ownership-gated calls MUST use make_account_headers(account_id). The shared
constant is only a fallback for tests that never exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("platform-admin-1", "PlatformAdmin"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "account_headers": build_user_headers("test-account-1", "Account"),
    "advisor_headers": build_user_headers("advisor-1", "Advisor"),
    "psap_operator_headers": build_user_headers("psap-operator-1", "PSAPOperator"),
    "law_enforcement_headers": build_user_headers("le-officer-1", "LawEnforcement"),
    "emergency_operator_headers": build_user_headers("eo-ops-1", "EmergencyOperator"),
    "dealer_service_headers": build_user_headers("dealer-service-1", "DealerService"),
    "billing_admin_headers": build_user_headers("billing-admin-1", "BillingAdmin"),
    "system_ingestion_headers": build_user_headers("system-ingestion-1", "SystemIngestion"),
}


def make_account_headers(user_id: str) -> dict:
    """For the entity-backed Account role. Pass the actual Account.id as user_id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Account")


def make_law_enforcement_headers(user_id: str) -> dict:
    """LawEnforcement with a specific operator id (opaque identity)."""
    return build_user_headers(user_id, "LawEnforcement")


def make_emergency_operator_headers(user_id: str) -> dict:
    """EmergencyOperator with a specific operator id (opaque identity)."""
    return build_user_headers(user_id, "EmergencyOperator")
