"""Pre-built role headers for every role declared in the PRD.

Seven of the eight roles are opaque operator identities, so a shared constant
is the canonical form for them. ``LicensedAgent`` is the one entity-backed
role: its ``X-User-ID`` must be a real ``Agent`` id, so any ownership-gated
call must use ``make_licensed_agent_headers(agent["id"])`` rather than the
shared constant.
"""
from prd_bench_local_runner.testing import build_user_headers


TEST_USERS = {
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "director_of_sales_headers": build_user_headers("test-director-1", "DirectorOfSales"),
    "compliance_officer_headers": build_user_headers("test-compliance-1", "ComplianceOfficer"),
    "licensing_coordinator_headers": build_user_headers("test-licensing-1", "LicensingCoordinator"),
    "coach_headers": build_user_headers("test-coach-1", "Coach"),
    "carrier_integration_headers": build_user_headers("test-carrier-1", "CarrierIntegration"),
    # entity_backed role: shared constant is a fallback for non-ownership tests only.
    "licensed_agent_headers": build_user_headers("test-agent-1", "LicensedAgent"),
    "any_headers": build_user_headers("test-any-1", "Any"),
}


def make_licensed_agent_headers(agent_id: str) -> dict:
    """For LicensedAgent (entity_backed:Agent).

    Pass the actual Agent.id as ``user_id`` whenever the call is
    ownership-gated (call sessions, scopes of appointment, enrollments).
    """
    return build_user_headers(agent_id, "LicensedAgent")


__all__ = ["TEST_USERS", "make_licensed_agent_headers"]