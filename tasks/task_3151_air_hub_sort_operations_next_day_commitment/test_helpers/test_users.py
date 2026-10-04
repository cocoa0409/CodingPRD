"""Pre-built role headers for every role in the PRD.

Every one of the ten roles has an opaque identity: no ownership comparison
exists anywhere in this API, and ``X-User-ID`` is never compared to an entity's
``id``. The shared constants below are therefore usable by every test, including
tests that mutate a resource.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "hub_ops_manager_headers": build_user_headers("test-hub-ops-1", "HubOpsManager"),
    "sort_supervisor_headers": build_user_headers("test-sort-supervisor-1", "SortSupervisor"),
    "sort_operator_headers": build_user_headers("test-sort-operator-1", "SortOperator"),
    "load_planner_headers": build_user_headers("test-load-planner-1", "LoadPlanner"),
    "commitment_controller_headers": build_user_headers("test-commitment-1", "CommitmentController"),
    "feeder_coordinator_headers": build_user_headers("test-feeder-1", "FeederCoordinator"),
    "gateway_coordinator_headers": build_user_headers("test-gateway-1", "GatewayCoordinator"),
    "hazmat_certifier_headers": build_user_headers("test-hazmat-1", "HazmatCertifier"),
    "weather_officer_headers": build_user_headers("test-weather-1", "WeatherOfficer"),
    "refund_adjuster_headers": build_user_headers("test-refund-1", "RefundAdjuster"),
}

# Alias kept for readability in fixtures.
ALL_ROLES = list(TEST_USERS.keys())


def headers_for(role: str, user_id: str = "test-operator-1") -> dict:
    """Build headers for an arbitrary role string — used for negative auth probes."""
    return build_user_headers(user_id, role)


def headers_without_role() -> dict:
    """Headers carrying only a user id, for the missing-role authentication probe."""
    return {"X-User-ID": "test-operator-1", "Content-Type": "application/json"}


def make_hub_ops_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "HubOpsManager")


def make_sort_supervisor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SortSupervisor")


def make_sort_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SortOperator")


def make_load_planner_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "LoadPlanner")


def make_commitment_controller_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CommitmentController")


def make_feeder_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FeederCoordinator")


def make_gateway_coordinator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "GatewayCoordinator")


def make_hazmat_certifier_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "HazmatCertifier")


def make_weather_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "WeatherOfficer")


def make_refund_adjuster_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "RefundAdjuster")