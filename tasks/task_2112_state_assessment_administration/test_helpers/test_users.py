"""Pre-built role headers for every role in the PRD.

Per PRD §2.1 the StateAssessmentOfficer's X-User-ID is an opaque operator
identifier, while DistrictTestCoordinator, SchoolTestCoordinator and Proctor
are entity-backed: their X-User-ID must equal the acting District / School /
Proctor id whenever the call is ownership-gated. The shared TEST_USERS
constants for those three roles are only safe for tests whose outcome does not
depend on ownership (missing-header, bad-payload, unknown-resource cases).
"""
from prd_bench_local_runner.testing import build_user_headers

OFFICER_USER_ID = "sao-001"

TEST_USERS = {
    # Opaque role — the shared constant is the canonical form.
    "officer_headers": build_user_headers(OFFICER_USER_ID, "StateAssessmentOfficer"),
    # Entity-backed roles: fallbacks for non-ownership tests only.
    "district_coordinator_headers": build_user_headers(
        "test-district-1", "DistrictTestCoordinator"),
    "school_coordinator_headers": build_user_headers(
        "test-school-1", "SchoolTestCoordinator"),
    "proctor_headers": build_user_headers("test-proctor-1", "Proctor"),
}


def make_officer_headers(user_id: str = OFFICER_USER_ID) -> dict:
    """StateAssessmentOfficer identity is opaque and never ownership-checked."""
    return build_user_headers(user_id, "StateAssessmentOfficer")


def make_district_coordinator_headers(user_id: str) -> dict:
    """DistrictTestCoordinator — pass the acting District.id as user_id."""
    return build_user_headers(user_id, "DistrictTestCoordinator")


def make_school_coordinator_headers(user_id: str) -> dict:
    """SchoolTestCoordinator — pass the acting School.id as user_id."""
    return build_user_headers(user_id, "SchoolTestCoordinator")


def make_proctor_headers(user_id: str) -> dict:
    """Proctor — pass the acting Proctor.id as user_id."""
    return build_user_headers(user_id, "Proctor")
