"""Pre-built role headers for every role in the PRD (§2.1).

StoreOperator is entity-backed: its X-User-ID must equal the Store.id being
operated on. Use make_store_operator_headers(store["id"]) for any
ownership-gated call; the shared TEST_USERS entry is a fallback for tests
that do not exercise ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "placement_manager_headers": build_user_headers("test-pm-1", "PlacementManager"),
    # entity_backed:Store — fallback only; prefer make_store_operator_headers(store_id).
    "store_operator_headers": build_user_headers("test-store-op-1", "StoreOperator"),
    "service_dispatcher_headers": build_user_headers("test-dispatcher-1", "ServiceDispatcher"),
    "field_technician_headers": build_user_headers("test-tech-1", "FieldTechnician"),
    "logistics_coordinator_headers": build_user_headers("test-logistics-1", "LogisticsCoordinator"),
    "production_planner_headers": build_user_headers("test-planner-1", "ProductionPlanner"),
}


def make_store_operator_headers(store_id: str) -> dict:
    """StoreOperator is entity-backed (PRD §2.1): X-User-ID must equal the
    Store.id for ownership-gated calls (telemetry, date-check sweep)."""
    return build_user_headers(store_id, "StoreOperator")


def make_platform_admin_headers(user_id: str) -> dict:
    """PlatformAdmin with a specific operator id (used for segregation-of-duties
    scenarios where the approver id matters)."""
    return build_user_headers(user_id, "PlatformAdmin")


def make_production_planner_headers(user_id: str) -> dict:
    """ProductionPlanner with a specific operator id (capacity-project creator)."""
    return build_user_headers(user_id, "ProductionPlanner")
