"""Pre-built role headers for every role the PRD declares.

PRD §2.1: "for all six roles ... `X-User-ID` is an opaque maintenance-department
badge identifier and is never the `id` of a persisted entity" and "it never
compares `X-User-ID` to any entity's `id`, and no resource in this system is
'owned' by its caller in an ownership-check sense".

No role is entity-backed, so the shared constants below are always a legitimate
identity. The per-badge builders exist because one rule *does* compare a stored
badge against the live caller — the segregation-of-duties rule at inspection
sign-off (PRD §3.3) — and because audit stamps such as `signed_off_by_user_id`
and `recorded_by_user_ids` are asserted by badge value.
"""

from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "park_ops_admin_headers": build_user_headers("admin-1", "ParkOpsAdmin"),
    "maintenance_manager_headers": build_user_headers("mgr-1", "MaintenanceManager"),
    "maintenance_technician_headers": build_user_headers(
        "tech-1", "MaintenanceTechnician"
    ),
    "qualified_inspector_headers": build_user_headers("insp-1", "QualifiedInspector"),
    "safety_officer_headers": build_user_headers("safety-1", "SafetyOfficer"),
    "ride_operator_headers": build_user_headers("op-1", "RideOperator"),
}


def make_park_ops_admin_headers(user_id: str) -> dict:
    """Headers for a specific ParkOpsAdmin badge."""
    return build_user_headers(user_id, "ParkOpsAdmin")


def make_maintenance_manager_headers(user_id: str) -> dict:
    """Headers for a specific MaintenanceManager badge."""
    return build_user_headers(user_id, "MaintenanceManager")


def make_maintenance_technician_headers(user_id: str) -> dict:
    """Headers for a specific MaintenanceTechnician badge.

    Use this whenever the badge value itself is under assertion — the badge is
    appended to `recorded_by_user_ids` and later compared at sign-off.
    """
    return build_user_headers(user_id, "MaintenanceTechnician")


def make_qualified_inspector_headers(user_id: str) -> dict:
    """Headers for a specific QualifiedInspector badge.

    Use this whenever the signing badge must differ from (or deliberately match)
    a badge already present in `recorded_by_user_ids`.
    """
    return build_user_headers(user_id, "QualifiedInspector")


def make_safety_officer_headers(user_id: str) -> dict:
    """Headers for a specific SafetyOfficer badge."""
    return build_user_headers(user_id, "SafetyOfficer")


def make_ride_operator_headers(user_id: str) -> dict:
    """Headers for a specific RideOperator badge."""
    return build_user_headers(user_id, "RideOperator")


def make_headers(user_id: str, role: str) -> dict:
    """Headers for an arbitrary badge / role pair.

    Used by the authentication probes, which deliberately send a blank role, a
    blank badge, or a role that is not one of the six the PRD declares.
    """
    return build_user_headers(user_id, role)


# Convenience aliases used across the suite.
ADMIN = TEST_USERS["park_ops_admin_headers"]
MANAGER = TEST_USERS["maintenance_manager_headers"]
TECHNICIAN = TEST_USERS["maintenance_technician_headers"]
INSPECTOR = TEST_USERS["qualified_inspector_headers"]
SAFETY_OFFICER = TEST_USERS["safety_officer_headers"]
OPERATOR = TEST_USERS["ride_operator_headers"]
