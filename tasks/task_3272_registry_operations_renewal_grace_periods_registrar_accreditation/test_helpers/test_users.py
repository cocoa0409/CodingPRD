"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that do not exercise
# ownership. RegistrarOperator is entity_backed:Registrar, so its shared
# constant is only a fallback for non-ownership tests.
TEST_USERS = {
    "admin_headers": build_user_headers("test-admin-1", "RegistryAdmin"),
    "operator_headers": build_user_headers("test-operator-1", "RegistrarOperator"),
    "finance_headers": build_user_headers("test-finance-1", "RegistryFinance"),
    "abuse_headers": build_user_headers("test-abuse-1", "AbuseAnalyst"),
}


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    """RegistryAdmin is opaque; any stable id works."""
    return build_user_headers(user_id, "RegistryAdmin")


def make_operator_headers(registrar_id: str) -> dict:
    """RegistrarOperator is entity_backed:Registrar. Pass the actual
    Registrar.id whenever the call is ownership-gated (transfers, domain
    mutations on sponsored domains)."""
    return build_user_headers(registrar_id, "RegistrarOperator")


def make_finance_headers(user_id: str = "test-finance-1") -> dict:
    """RegistryFinance is opaque; any stable id works."""
    return build_user_headers(user_id, "RegistryFinance")


def make_abuse_headers(user_id: str = "test-abuse-1") -> dict:
    """AbuseAnalyst is opaque; any stable id works."""
    return build_user_headers(user_id, "AbuseAnalyst")
