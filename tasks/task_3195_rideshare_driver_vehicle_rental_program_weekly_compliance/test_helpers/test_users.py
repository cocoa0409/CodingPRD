"""Pre-built role headers for every role in the programme.

The Driver role is entity-backed: `X-User-ID` is the `id` of the acting Driver,
so ownership-gated calls must carry the real driver id. The four operator roles
are opaque: `X-User-ID` is an operator identifier not tied to any entity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — canonical for opaque roles, and safe for Driver calls that
# do not exercise ownership.
TEST_USERS = {
    "driver_headers": build_user_headers("test-driver-1", "Driver"),
    "fleet_ops_headers": build_user_headers("test-fleet-ops-1", "FleetOpsAgent"),
    "compliance_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "support_headers": build_user_headers("test-support-1", "SupportAgent"),
}


def make_driver_headers(driver_id: str) -> dict:
    """Headers for the Driver role (entity-backed by Driver).

    Pass the acting driver's own `id` whenever the call is ownership-gated
    (withdrawing an enrolment, and electing, funding or withdrawing a purchase
    option).
    """
    return build_user_headers(driver_id, "Driver")


def make_unknown_role_headers(user_id: str = "test-auditor-1", role: str = "Auditor") -> dict:
    """Headers naming a capacity outside the five recognised roles."""
    return build_user_headers(user_id, role)