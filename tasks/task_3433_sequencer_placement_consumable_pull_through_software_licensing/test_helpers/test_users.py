"""Pre-built role headers for every role in the PRD (section 2.1).

Shared constants in TEST_USERS are safe for opaque roles and for tests that do
not exercise ownership. For LabOperator (whose X-User-ID IS the acting
account's id) and for any segregation-of-duties flow, use the per-instance
builders with a specific user id.
"""
from prd_bench_local_runner.testing import build_user_headers

__all__ = [
    "TEST_USERS",
    "NO_AUTH_HEADERS",
    "make_platform_admin_headers",
    "make_account_manager_headers",
    "make_finance_admin_headers",
    "make_field_service_engineer_headers",
    "make_supply_planner_headers",
    "make_lab_operator_headers",
]

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "account_manager_headers": build_user_headers("test-account-manager-1", "AccountManager"),
    "finance_admin_headers": build_user_headers("test-finance-admin-1", "FinanceAdmin"),
    "field_service_engineer_headers": build_user_headers(
        "test-field-service-engineer-1", "FieldServiceEngineer"
    ),
    "supply_planner_headers": build_user_headers("test-supply-planner-1", "SupplyPlanner"),
    # Fallback only: LabOperator is entity-backed by Account, so ownership-gated
    # calls MUST use make_lab_operator_headers(account["id"]) instead.
    "lab_operator_headers": build_user_headers("test-lab-operator-1", "LabOperator"),
}

# Headers with no auth material at all — for unauthenticated-request tests.
NO_AUTH_HEADERS: dict = {}


def make_platform_admin_headers(user_id: str) -> dict:
    """PlatformAdmin headers with a specific operator id (opaque identity)."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_account_manager_headers(user_id: str) -> dict:
    """AccountManager headers with a specific operator id. Use distinct ids for
    segregation-of-duties flows (program/transition creator vs approver)."""
    return build_user_headers(user_id, "AccountManager")


def make_finance_admin_headers(user_id: str) -> dict:
    """FinanceAdmin headers with a specific operator id (approver/appraiser)."""
    return build_user_headers(user_id, "FinanceAdmin")


def make_field_service_engineer_headers(user_id: str) -> dict:
    """FieldServiceEngineer headers with a specific operator id."""
    return build_user_headers(user_id, "FieldServiceEngineer")


def make_supply_planner_headers(user_id: str) -> dict:
    """SupplyPlanner headers with a specific operator id."""
    return build_user_headers(user_id, "SupplyPlanner")


def make_lab_operator_headers(user_id: str) -> dict:
    """LabOperator headers. MANDATORY pattern: pass the owning Account's id as
    user_id for every ownership-gated call (order create/submit/cancel/return,
    run records, auto-scoped list reads)."""
    return build_user_headers(user_id, "LabOperator")
