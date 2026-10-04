"""Pre-built role headers for every role in the PRD.

The Carrier role is entity-backed (``X-User-ID`` is the acting Carrier record's
``id``); the shared carrier constant is only usable where no ownership binding
is exercised. All other roles have opaque identities, so their shared constants
are canonical for every call.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-admin-1", "PlatformAdmin"),
    "ams_headers": build_user_headers("test-ams-1", "AddressManagementSpecialist"),
    "supervisor_headers": build_user_headers("sup-maria", "RouteSupervisor"),
    "postmaster_headers": build_user_headers("pm-owens", "Postmaster"),
    "csr_headers": build_user_headers("test-csr-1", "CustomerServiceRep"),
    "standards_admin_headers": build_user_headers("test-ssa-1", "ServiceStandardsAdmin"),
    # Fallback only — never use where a Carrier.id ownership check applies.
    "carrier_headers": build_user_headers("test-carrier-1", "Carrier"),
}

ALL_ROLES = list(TEST_USERS.keys())


def headers_for(role: str, user_id: str = "test-operator-1") -> dict:
    """Build headers for an arbitrary role string — used for negative auth probes."""
    return build_user_headers(user_id, role)


def headers_without_credentials() -> dict:
    """No auth headers at all — the Anonymous probe."""
    return {"Content-Type": "application/json"}


def make_carrier_headers(user_id: str) -> dict:
    """For Carrier (entity_backed:Carrier). Pass the actual Carrier.id whenever
    the call is ownership-gated (scan events, mark-vacant, complete-early)."""
    return build_user_headers(user_id, "Carrier")


def make_supervisor_headers(user_id: str) -> dict:
    """RouteSupervisor headers with an explicit operator id (used to control
    submitter_user_id in segregation-of-duties scenarios)."""
    return build_user_headers(user_id, "RouteSupervisor")


def make_postmaster_headers(user_id: str) -> dict:
    """Postmaster headers with an explicit operator id (used to control
    approver_user_id in segregation-of-duties scenarios)."""
    return build_user_headers(user_id, "Postmaster")


def make_platform_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PlatformAdmin")


def make_ams_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "AddressManagementSpecialist")


def make_csr_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CustomerServiceRep")


def make_standards_admin_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ServiceStandardsAdmin")
