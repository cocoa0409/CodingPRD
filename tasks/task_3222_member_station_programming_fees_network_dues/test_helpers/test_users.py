"""Pre-built role headers for every role in the PRD (PRD §2.1).

`StationManager` is the only entity-backed role: its `X-User-ID` is the `id` of
the acting `MemberStation`, and ownership checks compare a resource's foreign-key
field to that value. Fixtures must therefore call `make_station_manager_headers`
with the actual station's `id` for any ownership-gated call. The shared constant
is a fallback for calls whose success does not depend on ownership.
"""
from prd_bench_local_runner.testing import build_user_headers

TEST_USERS = {
    # Entity-backed role: shared constant is a fallback for non-ownership tests only.
    "station_manager_headers": build_user_headers("test-station-manager-1", "StationManager"),
    # Opaque roles: the shared constant is the canonical form.
    "platform_admin_headers": build_user_headers("test-platform-admin-1", "PlatformAdmin"),
    "auditor_headers": build_user_headers("test-auditor-1", "NetworkComplianceAuditor"),
    "scheduler_headers": build_user_headers("test-scheduler-1", "NetworkScheduler"),
    "program_editor_headers": build_user_headers("test-program-editor-1", "NationalProgramEditor"),
    "underwriting_headers": build_user_headers("test-underwriting-1", "UnderwritingCoordinator"),
    "governance_headers": build_user_headers("test-governance-1", "NetworkGovernanceOfficer"),
}

# An unrecognised capacity, used to exercise the authentication gate.
UNKNOWN_ROLE_HEADERS = build_user_headers("test-unknown-1", "UnknownRole")

# No headers at all, used to exercise the missing-auth gate.
ANONYMOUS_HEADERS = {}


def make_station_manager_headers(station_id: str) -> dict:
    """Headers for a StationManager acting on `station_id`.

    Pass the actual MemberStation.id whenever the call is ownership-gated —
    a synthetic identifier never equals any real station's id, and every
    ownership check would then reject the request.
    """
    return build_user_headers(station_id, "StationManager")