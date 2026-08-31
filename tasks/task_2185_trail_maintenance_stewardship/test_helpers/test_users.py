"""Pre-built role headers for every role in the PRD (section 2.1)."""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    COORDINATOR_USER_ID,
    GRANTS_ADMIN_USER_ID,
    SAFETY_OFFICER_ALT_USER_ID,
    SAFETY_OFFICER_USER_ID,
)

# Shared constants.  Safe for the three opaque operator roles, and for tests
# that never exercise an ownership comparison.
TEST_USERS = {
    "coordinator_headers": build_user_headers(
        COORDINATOR_USER_ID, "StewardshipCoordinator"
    ),
    "safety_officer_headers": build_user_headers(
        SAFETY_OFFICER_USER_ID, "SafetyOfficer"
    ),
    "safety_officer_alt_headers": build_user_headers(
        SAFETY_OFFICER_ALT_USER_ID, "SafetyOfficer"
    ),
    "grants_admin_headers": build_user_headers(
        GRANTS_ADMIN_USER_ID, "GrantsAdministrator"
    ),
    # Fallbacks for the entity-backed roles.  Only use these where the call is
    # not ownership-gated.
    "volunteer_headers": build_user_headers("test-volunteer-1", "Volunteer"),
    "crew_leader_headers": build_user_headers("test-crew-leader-1", "CrewLeader"),
    "land_manager_headers": build_user_headers(
        "test-land-manager-1", "LandManagerOfficer"
    ),
}


def make_volunteer_headers(volunteer_id: str) -> dict:
    """For a Volunteer.  Pass the acting VolunteerProfile id as X-User-ID."""
    return build_user_headers(volunteer_id, "Volunteer")


def make_crew_leader_headers(volunteer_id: str) -> dict:
    """For a CrewLeader.  Pass the acting VolunteerProfile id as X-User-ID."""
    return build_user_headers(volunteer_id, "CrewLeader")


def make_land_manager_headers(land_manager_id: str) -> dict:
    """For a LandManagerOfficer.  Pass the acting LandManager id as X-User-ID."""
    return build_user_headers(land_manager_id, "LandManagerOfficer")


def make_coordinator_headers(user_id: str = COORDINATOR_USER_ID) -> dict:
    """For a StewardshipCoordinator (opaque operator identity)."""
    return build_user_headers(user_id, "StewardshipCoordinator")


def make_safety_officer_headers(user_id: str = SAFETY_OFFICER_USER_ID) -> dict:
    """For a SafetyOfficer (opaque operator identity)."""
    return build_user_headers(user_id, "SafetyOfficer")


def make_grants_admin_headers(user_id: str = GRANTS_ADMIN_USER_ID) -> dict:
    """For a GrantsAdministrator (opaque operator identity)."""
    return build_user_headers(user_id, "GrantsAdministrator")


NO_AUTH_HEADERS = {"Content-Type": "application/json"}
