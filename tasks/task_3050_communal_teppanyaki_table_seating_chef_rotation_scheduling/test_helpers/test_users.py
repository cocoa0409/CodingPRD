"""Pre-built role headers for the five roles the API recognises.

PlatformAdmin, FloorManager and Host are unbacked operators, so their shared
constants are canonical. Chef and SushiChef are entity-backed on ChefAssignment:
their X-User-ID is compared to the acting ChefAssignment's id, so ownership-gated
calls must use the per-instance builders below with a real chef id.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "floor_manager_headers": build_user_headers("test-floor-manager-1", "FloorManager"),
    "host_headers": build_user_headers("test-host-1", "Host"),
    # entity_backed:ChefAssignment — fallback constant for non-ownership calls only.
    "chef_headers": build_user_headers("test-chef-1", "Chef"),
    # entity_backed:ChefAssignment — fallback constant for non-ownership calls only.
    "sushi_chef_headers": build_user_headers("test-sushi-chef-1", "SushiChef"),
}


def make_chef_headers(user_id: str) -> dict:
    """For Chef (entity_backed:ChefAssignment). Pass the acting ChefAssignment.id
    whenever the call is ownership-gated."""
    return build_user_headers(user_id, "Chef")


def make_sushi_chef_headers(user_id: str) -> dict:
    """For SushiChef (entity_backed:ChefAssignment). Pass the acting
    ChefAssignment.id whenever the call is ownership-gated."""
    return build_user_headers(user_id, "SushiChef")