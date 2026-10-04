"""Role headers for every role, and per-instance builders for entity-backed roles.

Five roles are opaque operator identities that are never compared to a persisted
entity. The `Resident` role is entity-backed: `X-User-ID` must be the `id` of the
acting Resident, and ownership checks compare it to a resource's resident
foreign-key field. Fixtures therefore build resident headers with
`make_resident_headers(actual_resident_id)`.
"""

from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles and for calls that are not
# ownership-gated. Resident's constant is a fallback for non-ownership tests only.
TEST_USERS = {
    "platform_admin_headers": build_user_headers("op-admin-1", "PlatformAdmin"),
    "property_manager_headers": build_user_headers("op-manager-1", "PropertyManager"),
    "hardware_technician_headers": build_user_headers("op-hardware-1", "HardwareTechnician"),
    "maintenance_technician_headers": build_user_headers("op-maint-1", "MaintenanceTechnician"),
    "leasing_agent_headers": build_user_headers("op-leasing-1", "LeasingAgent"),
    "resident_headers": build_user_headers("resident-placeholder", "Resident"),
}

# Aliases kept for readability at call sites.
ADMIN = TEST_USERS["platform_admin_headers"]
MANAGER = TEST_USERS["property_manager_headers"]
HARDWARE = TEST_USERS["hardware_technician_headers"]
MAINTENANCE = TEST_USERS["maintenance_technician_headers"]
LEASING = TEST_USERS["leasing_agent_headers"]


def make_resident_headers(user_id: str) -> dict:
    """The Resident role is entity-backed: pass the actual Resident.id whenever
    the call is ownership-gated (guest-pass issuance or extension)."""
    return build_user_headers(user_id, "Resident")


def make_operator_headers(user_id: str, role: str) -> dict:
    """Build headers for an opaque operator identity."""
    return build_user_headers(user_id, role)


def unauthenticated_headers() -> dict:
    """Headers carrying no identity at all."""
    return {"Content-Type": "application/json"}


def unknown_role_headers() -> dict:
    """Headers carrying a role the platform does not recognize."""
    return build_user_headers("op-unknown-1", "BuildingSupervisor")