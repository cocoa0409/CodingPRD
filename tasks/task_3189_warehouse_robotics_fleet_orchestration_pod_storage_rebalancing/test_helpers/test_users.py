"""Pre-built role headers for every role in the PRD.

All roles in this system use opaque X-User-ID identifiers (PRD §2.1):
the server never compares X-User-ID to any entity id. Segregation-of-duties
checks compare the acting X-User-ID against the recorded X-User-ID of an
earlier step, so the triage/grant pair must use DISTINCT user ids.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for all roles in this PRD (identity is opaque).
TEST_USERS = {
    "fleet_admin_headers": build_user_headers("test-fleet-admin-1", "FleetAdmin"),
    "flow_controller_headers": build_user_headers(
        "test-flow-controller-1", "FlowController"
    ),
    "station_operator_headers": build_user_headers(
        "test-station-operator-1", "StationOperator"
    ),
    "floor_supervisor_headers": build_user_headers(
        "test-floor-supervisor-1", "FloorSupervisor"
    ),
    "safety_officer_headers": build_user_headers(
        "test-safety-officer-1", "SafetyOfficer"
    ),
    # A second safety officer with a distinct X-User-ID for
    # segregation-of-duties-clean flows (grant/record-validation must be
    # performed by an id different from the triaging supervisor's /
    # validating engineer's id).
    "safety_officer_2_headers": build_user_headers(
        "test-safety-officer-2", "SafetyOfficer"
    ),
    "maintenance_tech_headers": build_user_headers(
        "test-maintenance-tech-1", "MaintenanceTech"
    ),
    "release_engineer_headers": build_user_headers(
        "test-release-engineer-1", "ReleaseEngineer"
    ),
}


def make_fleet_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FleetAdmin")


def make_flow_controller_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FlowController")


def make_station_operator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "StationOperator")


def make_floor_supervisor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FloorSupervisor")


def make_safety_officer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "SafetyOfficer")


def make_maintenance_tech_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MaintenanceTech")


def make_release_engineer_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ReleaseEngineer")
