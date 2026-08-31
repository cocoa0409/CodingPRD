"""Pre-built role headers for every role in the PRD."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants. Six of the seven roles carry an opaque X-User-ID that the
# server never compares to any entity id, so a shared constant is canonical for
# them. CrewForeman is the one exception: its X-User-ID is the id of the acting
# Crew, so ownership-gated calls must use make_crew_foreman_headers(crew_id).
TEST_USERS = {
    "forester_headers": build_user_headers("forester-1", "UtilityForester"),
    "planner_headers": build_user_headers("planner-1", "ContractorPlanner"),
    "arborist_headers": build_user_headers("arborist-a", "CertifiedArborist"),
    "arborist_b_headers": build_user_headers("arborist-b", "CertifiedArborist"),
    "advocate_headers": build_user_headers("advocate-1", "CustomerAdvocate"),
    "analyst_headers": build_user_headers("analyst-1", "BillingAnalyst"),
    "admin_headers": build_user_headers("admin-1", "PlatformAdmin"),
    # Fallback only — never for a call that checks crew ownership.
    "foreman_headers": build_user_headers("foreman-1", "CrewForeman"),
}

ARBORIST_A_ID = "arborist-a"
ARBORIST_B_ID = "arborist-b"
FORESTER_ID = "forester-1"


def make_crew_foreman_headers(crew_id: str) -> dict:
    """Headers for a CrewForeman acting on behalf of one crew.

    X-User-ID is the id of the acting Crew, so pass the real crew id whenever
    the call is ownership-gated (filing production, recording a removal).
    """
    return build_user_headers(crew_id, "CrewForeman")


def make_arborist_headers(user_id: str) -> dict:
    """Headers for a CertifiedArborist with an explicit operator identity."""
    return build_user_headers(user_id, "CertifiedArborist")


def make_forester_headers(user_id: str = FORESTER_ID) -> dict:
    return build_user_headers(user_id, "UtilityForester")


def headers_for_role(role: str, user_id: str = "operator-1") -> dict:
    """Arbitrary role/identity pair — used by authorization tests."""
    return build_user_headers(user_id, role)
