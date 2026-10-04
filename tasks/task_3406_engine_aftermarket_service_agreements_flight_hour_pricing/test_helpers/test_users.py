"""Pre-built role headers for the five PRD §2.1 roles.

Identity semantics (PRD §2.1):
- Operator is entity-backed: X-User-ID must be the `id` of the acting Operator
  entity whenever the call is ownership-gated (report submission, visit
  scheduling, workscope approve/reject, lease reserve/activate/return).
  Use make_operator_headers(operator["id"]) for those calls.
- PlatformAdmin, ContractManager, ShopPlanner, FinanceController are opaque:
  X-User-ID is not compared to any entity id, so the shared constants are
  canonical for them.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Opaque roles — canonical shared form.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "contract_manager_headers": build_user_headers("test-contract-manager-1", "ContractManager"),
    "shop_planner_headers": build_user_headers("test-shop-planner-1", "ShopPlanner"),
    "finance_controller_headers": build_user_headers("test-finance-controller-1", "FinanceController"),
    # Entity-backed role — fallback ONLY for tests that do not exercise
    # ownership (e.g. role-rejection tests where the Operator role itself is
    # not allowed on the endpoint). Never use this for an ownership-gated
    # call: the id matches no real Operator and the call fails 403.
    "operator_headers": build_user_headers("test-operator-1", "Operator"),
}


def make_operator_headers(user_id: str) -> dict:
    """Headers for the entity-backed Operator role.

    Pass the actual Operator entity's `id` as user_id for every
    ownership-gated call (the server compares X-User-ID against the
    resource-owning operator, resolved through the engine chain).
    """
    return build_user_headers(user_id, "Operator")
