"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise
# ownership. DoorManager is entity-backed by Door; use make_door_manager_headers
# with the actual door id whenever the call is ownership-gated.
TEST_USERS = {
    "network_admin_headers": build_user_headers("test-network-admin-1", "NetworkAdmin"),
    "hub_manager_headers": build_user_headers("test-hub-manager-1", "HubManager"),
    "route_planner_headers": build_user_headers("test-route-planner-1", "RoutePlanner"),
    "route_driver_headers": build_user_headers("test-route-driver-1", "RouteDriver"),
    # entity_backed:Door — fallback for non-ownership tests only.
    "door_manager_headers": build_user_headers("test-door-manager-1", "DoorManager"),
}


def make_door_manager_headers(door_id: str) -> dict:
    """For DoorManager (entity_backed:Door). Pass the actual Door.id as
    door_id whenever the call is ownership-gated (mix plans, fundraiser
    orders, stale credits, hot-light windows)."""
    return build_user_headers(door_id, "DoorManager")
