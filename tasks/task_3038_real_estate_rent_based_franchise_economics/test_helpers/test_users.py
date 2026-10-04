"""Pre-built role headers for every role in the PRD.

FranchisorAdmin / FranchiseFinance / CoopManager carry an opaque X-User-ID,
so shared constants are canonical for them. Operator is entity-backed: its
X-User-ID must equal the acting Operator entity's id on ownership-gated
calls, so tests must use make_operator_headers(operator_id) there.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — shared constants are the canonical form.
    "admin_headers": build_user_headers("test-admin-1", "FranchisorAdmin"),
    "finance_headers": build_user_headers("test-finance-1", "FranchiseFinance"),
    "coop_headers": build_user_headers("test-coop-1", "CoopManager"),
    # Entity-backed role — fallback only for calls that do not exercise ownership.
    "operator_headers": build_user_headers("test-operator-1", "Operator"),
}


def make_operator_headers(operator_id: str) -> dict:
    """Operator is entity-backed: X-User-ID must equal the Operator entity's id
    whenever the call is ownership-gated (sales-report submit, spend submit)."""
    return build_user_headers(operator_id, "Operator")


def make_admin_headers(user_id: str = "test-admin-1") -> dict:
    return build_user_headers(user_id, "FranchisorAdmin")


def make_finance_headers(user_id: str = "test-finance-1") -> dict:
    return build_user_headers(user_id, "FranchiseFinance")


def make_coop_headers(user_id: str = "test-coop-1") -> dict:
    return build_user_headers(user_id, "CoopManager")
